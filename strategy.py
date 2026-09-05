"""
XUAN 3+1 策略邏輯 (Python 版本)
忠實移植自 Pine Script 版本的 XUAN3+1 指標核心邏輯：
- 結構判斷 (BOS / CHoCH)：用「leg」演算法偵測擺動高低點，用收盤價突破判斷結構
- 訂單塊 (Order Block)：不使用ATR過濾，直接用原始高低點
  - 多頭結構突破時：訂單塊 = 從「前一個擺動高點」到現在，中間最低點的那根K棒
  - 空頭結構突破時：訂單塊 = 從「前一個擺動低點」到現在，中間最高點的那根K棒
- FVG (失衡區)：經典3根K棒跳空公式，且要求跳空前一根是順勢的實體K棒
- 進場四條件：CHoCH + FVG + BOS (同方向，順序不限) + 收盤價收在「最新那個」訂單塊之外
  - 只有清單裡「最新的」訂單塊有資格觸發進場；一旦出現更新的訂單塊，舊的就算沒用過也作廢
  - 只要沒出現「反方向CHoCH」，這輪循環就一直有效
- 止損：抓「觸發這次訊號的訂單塊」的前一個(比較早形成的那個)；如果它就是最早那個，就用它自己
"""

from dataclasses import dataclass, field
from typing import Optional

ENTRY_OB_CAP = 5  # 每個方向最多保留幾個訂單塊 (跟指標一致)


@dataclass
class Signal:
    index: int          # 觸發訊號的K棒索引 (0 = 最舊)
    direction: str       # 'long' or 'short'
    entry_price: float
    sl_price: float
    candle_time: int     # 該K棒的收盤時間戳 (毫秒)


@dataclass
class _Pivot:
    level: Optional[float] = None
    crossed: bool = True
    bar_idx: Optional[int] = None


def compute_signals(candles: list, swing_len: int = 5) -> list:
    """
    candles: [[timestamp_ms, open, high, low, close, volume], ...]，由舊到新排序，
             且必須是「已經收盤」的K棒（呼叫端要自行濾掉還在跑的那一根）。
    swing_len: 對應指標的擺動高低點週期 (預設5，跟指標一致)。

    回傳: list[Signal]，包含這段資料裡所有觸發過的訊號 (通常呼叫端只關心
          最後一根K棒 index == len(candles)-1 是否有新訊號)。
    """
    n = len(candles)
    if n < swing_len * 3:
        return []

    ts    = [c[0] for c in candles]
    open_ = [c[1] for c in candles]
    high  = [c[2] for c in candles]
    low   = [c[3] for c in candles]
    close = [c[4] for c in candles]

    leg_val = 0          # 0 = BEARISH_LEG, 1 = BULLISH_LEG
    swing_high = _Pivot()
    swing_low  = _Pivot()
    trend_bias = 0        # 0=未確立, 1=多頭, -1=空頭

    entry_bull_top: list = []
    entry_bull_bot: list = []
    entry_bull_used: list = []
    entry_bear_top: list = []
    entry_bear_bot: list = []
    entry_bear_used: list = []

    bull_choch_flag = bull_fvg_flag = bull_bos_flag = False
    bear_choch_flag = bear_fvg_flag = bear_bos_flag = False

    signals: list = []

    for i in range(n):
        # ---------------- 擺動高低點 (leg) ----------------
        if i - swing_len >= 0:
            window_start = max(0, i - swing_len + 1)
            hh = max(high[window_start:i + 1])
            ll = min(low[window_start:i + 1])
            old_high = high[i - swing_len]
            old_low  = low[i - swing_len]

            new_leg_high = old_high > hh
            new_leg_low  = old_low < ll

            prev_leg = leg_val
            if new_leg_high:
                leg_val = 0
            elif new_leg_low:
                leg_val = 1

            if leg_val != prev_leg:
                if leg_val == 1:
                    swing_low = _Pivot(level=old_low, crossed=False, bar_idx=i - swing_len)
                else:
                    swing_high = _Pivot(level=old_high, crossed=False, bar_idx=i - swing_len)

        # ---------------- 結構判斷 (BOS / CHoCH) ----------------
        bull_choch = bull_bos = bear_choch = bear_bos = False

        if i >= 1 and swing_high.level is not None and not swing_high.crossed:
            if close[i] > swing_high.level and close[i - 1] <= swing_high.level:
                swing_high.crossed = True
                is_choch = trend_bias == -1
                trend_bias = 1
                bull_choch = is_choch
                bull_bos = not is_choch

                start_idx = swing_high.bar_idx
                sub_low = low[start_idx:i + 1]
                ob_bar = start_idx + sub_low.index(min(sub_low))
                ob_top, ob_bot = high[ob_bar], low[ob_bar]

                entry_bull_top.insert(0, ob_top)
                entry_bull_bot.insert(0, ob_bot)
                entry_bull_used.insert(0, False)
                if len(entry_bull_top) > ENTRY_OB_CAP:
                    entry_bull_top.pop()
                    entry_bull_bot.pop()
                    entry_bull_used.pop()

        if i >= 1 and swing_low.level is not None and not swing_low.crossed:
            if close[i] < swing_low.level and close[i - 1] >= swing_low.level:
                swing_low.crossed = True
                is_choch2 = trend_bias == 1
                trend_bias = -1
                bear_choch = is_choch2
                bear_bos = not is_choch2

                start_idx = swing_low.bar_idx
                sub_high = high[start_idx:i + 1]
                ob_bar = start_idx + sub_high.index(max(sub_high))
                ob_top, ob_bot = high[ob_bar], low[ob_bar]

                entry_bear_top.insert(0, ob_top)
                entry_bear_bot.insert(0, ob_bot)
                entry_bear_used.insert(0, False)
                if len(entry_bear_top) > ENTRY_OB_CAP:
                    entry_bear_top.pop()
                    entry_bear_bot.pop()
                    entry_bear_used.pop()

        # ---------------- FVG ----------------
        bull_fvg = bear_fvg = False
        if i >= 2:
            if low[i] > high[i - 2] and close[i - 1] > high[i - 2] and (close[i - 1] - open_[i - 1]) > 0:
                bull_fvg = True
            if high[i] < low[i - 2] and close[i - 1] < low[i - 2] and (close[i - 1] - open_[i - 1]) < 0:
                bear_fvg = True

        # ---------------- 四條件旗標 (反方向CHoCH才重置) ----------------
        if bear_choch:
            bull_choch_flag = bull_fvg_flag = bull_bos_flag = False
            entry_bull_top.clear()
            entry_bull_bot.clear()
            entry_bull_used.clear()

        if bull_choch:
            bear_choch_flag = bear_fvg_flag = bear_bos_flag = False
            entry_bear_top.clear()
            entry_bear_bot.clear()
            entry_bear_used.clear()

        if bull_choch:
            bull_choch_flag = True
        if bull_fvg:
            bull_fvg_flag = True
        if bull_bos:
            bull_bos_flag = True

        if bear_choch:
            bear_choch_flag = True
        if bear_fvg:
            bear_fvg_flag = True
        if bear_bos:
            bear_bos_flag = True

        bull_trend_confirmed = bull_choch_flag and bull_fvg_flag and bull_bos_flag
        bear_trend_confirmed = bear_choch_flag and bear_fvg_flag and bear_bos_flag

        # ---------------- 進場訊號：只看最新的訂單塊 ----------------
        if i >= 1 and bull_trend_confirmed and entry_bull_top:
            ob_top = entry_bull_top[0]
            if not entry_bull_used[0] and close[i] > ob_top and close[i - 1] <= ob_top:
                entry_bull_used[0] = True
                sl = entry_bull_bot[1] if len(entry_bull_bot) > 1 else entry_bull_bot[0]
                signals.append(Signal(index=i, direction='long', entry_price=close[i], sl_price=sl, candle_time=ts[i]))

        if i >= 1 and bear_trend_confirmed and entry_bear_bot:
            ob_bot = entry_bear_bot[0]
            if not entry_bear_used[0] and close[i] < ob_bot and close[i - 1] >= ob_bot:
                entry_bear_used[0] = True
                sl = entry_bear_top[1] if len(entry_bear_top) > 1 else entry_bear_top[0]
                signals.append(Signal(index=i, direction='short', entry_price=close[i], sl_price=sl, candle_time=ts[i]))

    return signals


def get_latest_signal(candles: list, swing_len: int = 5) -> Optional[Signal]:
    """只關心『最後一根K棒』有沒有觸發新訊號，用於實際掃描時呼叫。"""
    if not candles:
        return None
    signals = compute_signals(candles, swing_len=swing_len)
    last_idx = len(candles) - 1
    for sig in signals:
        if sig.index == last_idx:
            return sig
    return None
