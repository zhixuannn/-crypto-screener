"""
賽克斯策略 (Vegas Channel + QQE MOD) - 狀態持久化版
移植自回測工具的 strategy_sykes.py，核心規則不變：

進場規則：
- 價格回測 Vegas 通道 (小通道 EMA144/169 或 大通道 EMA576/676) 但不收破，
  然後收盤重新站回 EMA12 過濾線之外，且 QQE MOD 訊號同方向 → 進場
出場規則：
- 停損：最近一個擺盪高/低點
- 停利：1:1 風險報酬比 (可調)

跟回測版本的差異：
- 擺盪高/低點的確認方式改成「即時可用」版本：需要等 lookback 根新K棒過去，
  才能確認幾根之前的那根是不是真正的高/低點 (回測版本用了未來資料，
  即時掃描不能這樣做，所以確認會延遲 lookback 根K棒，這是必要的修正)
"""

import json
from dataclasses import dataclass
from typing import Optional


@dataclass
class Signal:
    direction: str        # 'long' or 'short'
    entry_price: float
    sl_price: float
    tp_price: float
    candle_time: int


def new_state(swing_lookback: int = 5, rsi_len: int = 6, smooth: int = 5, threshold: float = 3.0) -> dict:
    """建立一個全新、空白的狀態 (新幣種/新時區第一次追蹤時使用)。"""
    return {
        'swing_lookback': swing_lookback,
        'rsi_len': rsi_len,
        'smooth': smooth,
        'threshold': threshold,
        'ema12': None, 'ema144': None, 'ema169': None, 'ema576': None, 'ema676': None,
        'prev_close': None,
        'roll_up': None, 'roll_down': None, 'rsi_ma': None,
        'swing_buffer': [],   # 最近的 [time, high, low] 用來確認擺盪高低點
        'last_swing_high': None,
        'last_swing_low': None,
    }


def state_to_json(state: dict) -> str:
    return json.dumps(state)


def state_from_json(state_json: str) -> dict:
    return json.loads(state_json)


def _update_ema(state: dict, key: str, period: int, price: float):
    alpha = 2.0 / (period + 1)
    if state[key] is None:
        state[key] = price
    else:
        state[key] = alpha * price + (1 - alpha) * state[key]


def _update_qqe(state: dict, close: float) -> int:
    """更新QQE狀態，回傳這根K棒的 qqe_signal (1=多頭色, -1=空頭色, 0=中性)。"""
    rsi_len = state['rsi_len']
    smooth = state['smooth']
    threshold = state['threshold']

    prev_close = state['prev_close']
    delta = 0.0 if prev_close is None else (close - prev_close)
    up = max(delta, 0.0)
    down = max(-delta, 0.0)

    alpha_rsi = 1.0 / rsi_len
    if state['roll_up'] is None:
        state['roll_up'] = up
        state['roll_down'] = down
    else:
        state['roll_up'] = alpha_rsi * up + (1 - alpha_rsi) * state['roll_up']
        state['roll_down'] = alpha_rsi * down + (1 - alpha_rsi) * state['roll_down']

    if state['roll_down'] == 0:
        rsi = 100.0 if state['roll_up'] > 0 else 50.0
    else:
        rs = state['roll_up'] / state['roll_down']
        rsi = 100.0 - (100.0 / (1.0 + rs))

    alpha_smooth = 2.0 / (smooth + 1)
    if state['rsi_ma'] is None:
        state['rsi_ma'] = rsi
    else:
        state['rsi_ma'] = alpha_smooth * rsi + (1 - alpha_smooth) * state['rsi_ma']

    state['prev_close'] = close

    rsi_centered = state['rsi_ma'] - 50
    if rsi_centered > threshold:
        return 1
    elif rsi_centered < -threshold:
        return -1
    return 0


def _touched_channel(state: dict, high: float, low: float, close: float) -> tuple:
    """回傳 (touched_from_above, touched_from_below) 這根K棒有沒有碰到通道但沒收破。"""
    touched_from_above = False
    touched_from_below = False

    small_top, small_bot = max(state['ema144'], state['ema169']), min(state['ema144'], state['ema169'])
    if low <= small_top and close > small_bot:
        touched_from_above = True
    if high >= small_bot and close < small_top:
        touched_from_below = True

    large_top, large_bot = max(state['ema576'], state['ema676']), min(state['ema576'], state['ema676'])
    if low <= large_top and close > large_bot:
        touched_from_above = True
    if high >= large_bot and close < large_top:
        touched_from_below = True

    return touched_from_above, touched_from_below


def _update_swing_points(state: dict, ts: int, high: float, low: float):
    """更新擺盪高低點的追蹤緩衝區，確認延遲 lookback 根K棒 (即時可用的正確做法)。"""
    lookback = state['swing_lookback']
    buf = state['swing_buffer']
    buf.append([ts, high, low])
    max_len = 2 * lookback + 1
    if len(buf) > max_len:
        buf.pop(0)

    if len(buf) == max_len:
        mid = buf[lookback]
        mid_high, mid_low = mid[1], mid[2]
        all_highs = [b[1] for b in buf]
        all_lows = [b[2] for b in buf]
        if mid_high == max(all_highs):
            state['last_swing_high'] = mid_high
        if mid_low == min(all_lows):
            state['last_swing_low'] = mid_low


def advance_state(state: dict, candles: list, rr: float = 1.0):
    """
    把一批「新出現的、已收盤」的K棒依序餵進狀態裡繼續運算。
    candles: [[timestamp_ms, open, high, low, close, volume], ...]，由舊到新排序。
    回傳: (更新後的狀態dict, 這批K棒裡新觸發的訊號list[Signal])
    """
    signals = []

    for candle in candles:
        ts, o, h, l, c = candle[0], candle[1], candle[2], candle[3], candle[4]

        _update_ema(state, 'ema12', 12, c)
        _update_ema(state, 'ema144', 144, c)
        _update_ema(state, 'ema169', 169, c)
        _update_ema(state, 'ema576', 576, c)
        _update_ema(state, 'ema676', 676, c)

        qqe_signal = _update_qqe(state, c)
        touched_from_above, touched_from_below = _touched_channel(state, h, l, c)
        _update_swing_points(state, ts, h, l)

        if (touched_from_above and c > state['ema12'] and qqe_signal == 1
                and state['last_swing_low'] is not None and state['last_swing_low'] < c):
            sl = state['last_swing_low']
            risk = c - sl
            if risk > 0:
                tp = c + risk * rr
                signals.append(Signal(direction='long', entry_price=c, sl_price=sl, tp_price=tp, candle_time=ts))

        elif (touched_from_below and c < state['ema12'] and qqe_signal == -1
                and state['last_swing_high'] is not None and state['last_swing_high'] > c):
            sl = state['last_swing_high']
            risk = sl - c
            if risk > 0:
                tp = c - risk * rr
                signals.append(Signal(direction='short', entry_price=c, sl_price=sl, tp_price=tp, candle_time=ts))

    return state, signals
