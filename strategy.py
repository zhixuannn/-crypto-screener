"""
XUAN 3+1 策略邏輯 (Python 版本，狀態持久化版)
與原版邏輯完全相同 (CHoCH+FVG+BOS+訂單塊四條件)，差別在於：
- 不再每次重新計算整批K棒，而是把「運算到一半的狀態」存起來，
  之後只需要把新出現的K棒一根一根餵進來繼續算，效果等同 Pine Script
  「從指標第一次加到圖表上就沒停過」的連續性
- 訂單塊改成「即時追蹤」：擺動高/低點一形成，就開始邊收K棒邊追蹤
  目前為止的最低點/最高點在哪根，等到真正被突破時直接拿來當作訂單塊
"""

import json
from dataclasses import dataclass
from typing import Optional

ENTRY_OB_CAP = 5


@dataclass
class Signal:
    direction: str        # 'long' or 'short'
    entry_price: float
    sl_price: float
    tp_price: float
    candle_time: int      # 觸發訊號那根K棒的時間戳 (毫秒)


def new_state(swing_len: int = 5) -> dict:
    """建立一個全新、空白的狀態 (新幣種第一次追蹤時使用)。"""
    return {
        'swing_len': swing_len,
        'leg_val': 0,
        'buffer': [],       # 最近幾根K棒 [[time,open,high,low,close], ...]
        'swing_high': None,  # {'level','bar_time','crossed','ob_bar_high','ob_bar_low','ob_bar_time'}
        'swing_low': None,
        'trend_bias': 0,
        'entry_bull_top': [], 'entry_bull_bot': [], 'entry_bull_used': [],
        'entry_bear_top': [], 'entry_bear_bot': [], 'entry_bear_used': [],
        'bull_choch_flag': False, 'bull_fvg_flag': False, 'bull_bos_flag': False,
        'bear_choch_flag': False, 'bear_fvg_flag': False, 'bear_bos_flag': False,
    }


def state_to_json(state: dict) -> str:
    return json.dumps(state)


def state_from_json(state_json: str) -> dict:
    return json.loads(state_json)


def advance_state(state: dict, candles: list, rr: float = 1.0):
    """
    把一批「新出現的、已收盤的」K棒依序餵進狀態裡繼續運算。
    candles: [[timestamp_ms, open, high, low, close, volume], ...]，由舊到新排序。
    回傳: (更新後的狀態dict, 這批K棒裡新觸發的訊號list[Signal])
    """
    swing_len = state['swing_len']
    buf = state['buffer']
    signals = []
    required_len = max(swing_len + 1, 3)

    for candle in candles:
        buf.append(list(candle[:5]))
        if len(buf) > required_len:
            buf.pop(0)
        n = len(buf)
        ts, o, h, l, c = buf[-1]
        prev_close = buf[-2][4] if n >= 2 else None

        # ---- 先更新「目前待突破的擺動點」的即時追蹤 (用這根新K棒) ----
        sh = state['swing_high']
        if sh is not None and not sh['crossed']:
            if l < sh['ob_bar_low']:
                sh['ob_bar_low'] = l
                sh['ob_bar_high'] = h
                sh['ob_bar_time'] = ts
        sw_low = state['swing_low']
        if sw_low is not None and not sw_low['crossed']:
            if h > sw_low['ob_bar_high']:
                sw_low['ob_bar_high'] = h
                sw_low['ob_bar_low'] = l
                sw_low['ob_bar_time'] = ts

        # ---- 擺動高低點 (leg) 判斷 ----
        if n >= swing_len + 1:
            window = buf[-swing_len:]
            hh = max(b[2] for b in window)
            ll = min(b[3] for b in window)
            old = buf[-(swing_len + 1)]
            old_time, old_o, old_high, old_low, old_close = old

            new_leg_high = old_high > hh
            new_leg_low = old_low < ll
            prev_leg = state['leg_val']
            if new_leg_high:
                state['leg_val'] = 0
            elif new_leg_low:
                state['leg_val'] = 1

            if state['leg_val'] != prev_leg:
                pivot_range = buf[-(swing_len + 1):]
                if state['leg_val'] == 1:
                    # 新的擺動低點形成 → 之後用來偵測「空頭結構突破」，訂單塊追蹤「最高的高點」
                    ob_candle = max(pivot_range, key=lambda b: b[2])
                    state['swing_low'] = {
                        'level': old_low, 'bar_time': old_time, 'crossed': False,
                        'ob_bar_high': ob_candle[2], 'ob_bar_low': ob_candle[3], 'ob_bar_time': ob_candle[0],
                    }
                else:
                    # 新的擺動高點形成 → 之後用來偵測「多頭結構突破」，訂單塊追蹤「最低的低點」
                    ob_candle = min(pivot_range, key=lambda b: b[3])
                    state['swing_high'] = {
                        'level': old_high, 'bar_time': old_time, 'crossed': False,
                        'ob_bar_high': ob_candle[2], 'ob_bar_low': ob_candle[3], 'ob_bar_time': ob_candle[0],
                    }

        # ---- 結構判斷 (BOS / CHoCH) ----
        bull_choch = bull_bos = bear_choch = bear_bos = False

        sh = state['swing_high']
        if sh is not None and not sh['crossed'] and prev_close is not None:
            if c > sh['level'] and prev_close <= sh['level']:
                sh['crossed'] = True
                is_choch = state['trend_bias'] == -1
                state['trend_bias'] = 1
                bull_choch, bull_bos = is_choch, not is_choch

                state['entry_bull_top'].insert(0, sh['ob_bar_high'])
                state['entry_bull_bot'].insert(0, sh['ob_bar_low'])
                state['entry_bull_used'].insert(0, False)
                if len(state['entry_bull_top']) > ENTRY_OB_CAP:
                    state['entry_bull_top'].pop()
                    state['entry_bull_bot'].pop()
                    state['entry_bull_used'].pop()

        sw_low = state['swing_low']
        if sw_low is not None and not sw_low['crossed'] and prev_close is not None:
            if c < sw_low['level'] and prev_close >= sw_low['level']:
                sw_low['crossed'] = True
                is_choch2 = state['trend_bias'] == 1
                state['trend_bias'] = -1
                bear_choch, bear_bos = is_choch2, not is_choch2

                state['entry_bear_top'].insert(0, sw_low['ob_bar_high'])
                state['entry_bear_bot'].insert(0, sw_low['ob_bar_low'])
                state['entry_bear_used'].insert(0, False)
                if len(state['entry_bear_top']) > ENTRY_OB_CAP:
                    state['entry_bear_top'].pop()
                    state['entry_bear_bot'].pop()
                    state['entry_bear_used'].pop()

        # ---- FVG ----
        bull_fvg = bear_fvg = False
        if n >= 3:
            b_prev2, b_prev1, b_cur = buf[-3], buf[-2], buf[-1]
            _, o1, h1, l1, c1 = b_prev1
            h_prev2, l_prev2 = b_prev2[2], b_prev2[3]
            _, _, _, l_cur, _ = b_cur[:5] if False else (None, None, None, buf[-1][3], None)
            h_cur, l_cur = buf[-1][2], buf[-1][3]
            if l_cur > h_prev2 and c1 > h_prev2 and (c1 - o1) > 0:
                bull_fvg = True
            if h_cur < l_prev2 and c1 < l_prev2 and (c1 - o1) < 0:
                bear_fvg = True

        # ---- 四條件旗標 (反方向CHoCH才重置) ----
        if bear_choch:
            state['bull_choch_flag'] = state['bull_fvg_flag'] = state['bull_bos_flag'] = False
            state['entry_bull_top'].clear(); state['entry_bull_bot'].clear(); state['entry_bull_used'].clear()
        if bull_choch:
            state['bear_choch_flag'] = state['bear_fvg_flag'] = state['bear_bos_flag'] = False
            state['entry_bear_top'].clear(); state['entry_bear_bot'].clear(); state['entry_bear_used'].clear()

        if bull_choch: state['bull_choch_flag'] = True
        if bull_fvg: state['bull_fvg_flag'] = True
        if bull_bos: state['bull_bos_flag'] = True
        if bear_choch: state['bear_choch_flag'] = True
        if bear_fvg: state['bear_fvg_flag'] = True
        if bear_bos: state['bear_bos_flag'] = True

        bull_trend_confirmed = state['bull_choch_flag'] and state['bull_fvg_flag'] and state['bull_bos_flag']
        bear_trend_confirmed = state['bear_choch_flag'] and state['bear_fvg_flag'] and state['bear_bos_flag']

        # ---- 進場訊號：只看最新的訂單塊 ----
        if bull_trend_confirmed and state['entry_bull_top'] and prev_close is not None:
            ob_top = state['entry_bull_top'][0]
            if not state['entry_bull_used'][0] and c > ob_top and prev_close <= ob_top:
                state['entry_bull_used'][0] = True
                sl = state['entry_bull_bot'][1] if len(state['entry_bull_bot']) > 1 else state['entry_bull_bot'][0]
                risk = c - sl
                tp = c + risk * rr
                signals.append(Signal(direction='long', entry_price=c, sl_price=sl, tp_price=tp, candle_time=ts))

        if bear_trend_confirmed and state['entry_bear_bot'] and prev_close is not None:
            ob_bot = state['entry_bear_bot'][0]
            if not state['entry_bear_used'][0] and c < ob_bot and prev_close >= ob_bot:
                state['entry_bear_used'][0] = True
                sl = state['entry_bear_top'][1] if len(state['entry_bear_top']) > 1 else state['entry_bear_top'][0]
                risk = sl - c
                tp = c - risk * rr
                signals.append(Signal(direction='short', entry_price=c, sl_price=sl, tp_price=tp, candle_time=ts))

    state['buffer'] = buf
    return state, signals
