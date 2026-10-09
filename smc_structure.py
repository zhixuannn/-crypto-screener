"""
SMC 結構判斷 (給訊號打『結構分』)，跟 XUAN 3+1 / TV 指標用「同一套」leg 演算法：
擺動高低點 = strategy.py 的 leg 判斷；BOS/CHoCH = 收盤價突破最近的擺動點。

兩種方法 (只用已收盤K棒)：
A. 最近一次 BOS／CHoCH 的方向：strategy.py 狀態裡的 trend_bias
   (1 = 最近一次是向上突破 / -1 = 向下突破 / 0 = 還沒出現)
B. 高低點排列：最近兩個擺動高點 + 最近兩個擺動低點
   都墊高 (HH + HL) = 多頭；都降低 (LH + LL) = 空頭；其餘 = 不明
"""

import strategy

SWING_LEN = 5
MIN_BARS = 40


def structure_state(candles: list, swing_len: int = SWING_LEN):
    """
    candles: [[ts, o, h, l, c, v], ...] 已收盤、由舊到新。
    回傳 dict(break_dir, arrangement)；資料不夠回傳 None。
    """
    if not candles or len(candles) < MIN_BARS:
        return None

    state = strategy.new_state(swing_len=swing_len)
    swing_highs, swing_lows = [], []
    seen_high = seen_low = None

    for candle in candles:
        state, _ = strategy.advance_state(state, [candle])
        sh = state['swing_high']
        if sh is not None and sh['bar_time'] != seen_high:
            seen_high = sh['bar_time']
            swing_highs.append(sh['level'])
        sl = state['swing_low']
        if sl is not None and sl['bar_time'] != seen_low:
            seen_low = sl['bar_time']
            swing_lows.append(sl['level'])

    bias = state['trend_bias']
    break_dir = 'bull' if bias == 1 else ('bear' if bias == -1 else None)

    arrangement = None
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        h1, h2 = swing_highs[-2], swing_highs[-1]
        l1, l2 = swing_lows[-2], swing_lows[-1]
        if h2 > h1 and l2 > l1:
            arrangement = 'bull'
        elif h2 < h1 and l2 < l1:
            arrangement = 'bear'

    return {'break_dir': break_dir, 'arrangement': arrangement}


_DIR_LABEL = {'bull': '多', 'bear': '空', None: '不明'}


def score_structure(direction: str, candles: list, max_points: float, break_weight: float = 0.6):
    """
    direction: 'long' / 'short'
    回傳 (分數, 說明)；資料不夠回傳 None。
    BOS/CHoCH 方向一致得 max*0.6，高低點排列一致得 max*0.4。
    """
    state = structure_state(candles)
    if state is None:
        return None
    want = 'bull' if direction == 'long' else 'bear'
    pts = 0.0
    if state['break_dir'] == want:
        pts += max_points * break_weight
    if state['arrangement'] == want:
        pts += max_points * (1 - break_weight)
    note = f"突破{_DIR_LABEL[state['break_dir']]}／排列{_DIR_LABEL[state['arrangement']]}"
    return round(pts), note
