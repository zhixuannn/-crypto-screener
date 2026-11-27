"""
流動性策略（Python 版，跟 TradingView「XUAN 流動性」同一套規則），狀態會存起來、一根一根接著算。

規則（做空；做多完全反過來）：
  1. 1H 或 4H「現在這根」K 棒的高點超過「前一根」的高點（掃前高）
  2. 掃完之後，價格跌破「現在這根」1H／4H 的開盤價（碰到就算，不用收盤）
  3. 同一根 1H／4H 裡，小週期（就是掃描的 5m／15m）先出現空方 FVG，之後出現空方 CHoCH
  4. 1～3 都完成的那根 K 棒收盤進場
  止損：前一根（已收盤的）6H K 棒高點；如果高點不在進場價上面（錯邊）就不記這筆
  止盈：1:1
  那根 1H／4H 收盤後，還沒完成的條件全部作廢；同一根裡如果又重新完成一次，可以再出訊號。
  日偏見順勢過濾不在這裡做（要抓日線），在 app.py 記錄前檢查。

結構（CHoCH）和 FVG 跟 3+1 用同一套：擺動長度 5，收盤價穿過擺動高／低點。
時間都用 UTC 切：1H、4H（0/4/8/...點）、6H（0/6/12/18 點），跟 TradingView 加密貨幣圖一樣。
"""

import json

from strategy import Signal

HTF_MS = {'1h': 3_600_000, '4h': 14_400_000}
SIX_H_MS = 21_600_000


def _new_htf():
    return {'idx': None, 'prev_h': None, 'prev_l': None, 'run_h': None, 'run_l': None, 'o': None,
            's_sweep': False, 's_open': False, 's_fvg': False, 's_choch': False,
            'l_sweep': False, 'l_open': False, 'l_fvg': False, 'l_choch': False}


def new_state(swing_len: int = 5) -> dict:
    return {
        'swing_len': swing_len,
        'last_time': None,
        'leg_val': 0,
        'buffer': [],
        'sh_level': None, 'sh_crossed': True,
        'sl_level': None, 'sl_crossed': True,
        'trend_bias': 0,
        'htf': {tf: _new_htf() for tf in HTF_MS},
        'six': {'idx': None, 'prev_h': None, 'prev_l': None, 'run_h': None, 'run_l': None},
    }


def state_to_json(state: dict) -> str:
    return json.dumps(state)


def state_from_json(s: str) -> dict:
    return json.loads(s)


def _reset(h, side):
    for k in ('sweep', 'open', 'fvg', 'choch'):
        h[f'{side}_{k}'] = False


def advance(state: dict, candles: list, rr: float = 1.0):
    """
    candles: 已收盤 K 棒 [[ts, o, h, l, c, ...], ...]（由舊到新）。比上次算過的還舊的會自動跳過。
    回傳 (state, [Signal])
    """
    swing_len = state['swing_len']
    buf = state['buffer']
    need = max(swing_len + 1, 3)
    out = []

    for candle in candles:
        ts, o, h, l, c = candle[:5]
        if state['last_time'] is not None and ts <= state['last_time']:
            continue
        state['last_time'] = ts
        buf.append([ts, o, h, l, c])
        if len(buf) > need:
            buf.pop(0)
        n = len(buf)
        prev_close = buf[-2][4] if n >= 2 else None

        # ---- 擺動高低點 ----
        if n >= swing_len + 1:
            window = buf[-swing_len:]
            hh = max(b[2] for b in window)
            ll = min(b[3] for b in window)
            old = buf[-(swing_len + 1)]
            prev_leg = state['leg_val']
            if old[2] > hh:
                state['leg_val'] = 0
            elif old[3] < ll:
                state['leg_val'] = 1
            if state['leg_val'] != prev_leg:
                if state['leg_val'] == 1:
                    state['sl_level'], state['sl_crossed'] = old[3], False
                else:
                    state['sh_level'], state['sh_crossed'] = old[2], False

        # ---- CHoCH ----
        bull_choch = bear_choch = False
        if state['sh_level'] is not None and not state['sh_crossed'] and prev_close is not None:
            if c > state['sh_level'] and prev_close <= state['sh_level']:
                state['sh_crossed'] = True
                bull_choch = state['trend_bias'] == -1
                state['trend_bias'] = 1
        if state['sl_level'] is not None and not state['sl_crossed'] and prev_close is not None:
            if c < state['sl_level'] and prev_close >= state['sl_level']:
                state['sl_crossed'] = True
                bear_choch = state['trend_bias'] == 1
                state['trend_bias'] = -1

        # ---- FVG ----
        bull_fvg = bear_fvg = False
        if n >= 3:
            p2, p1 = buf[-3], buf[-2]
            if l > p2[2] and p1[4] > p2[2] and p1[4] > p1[1]:
                bull_fvg = True
            if h < p2[3] and p1[4] < p2[3] and p1[4] < p1[1]:
                bear_fvg = True

        # ---- 前一根 6H 高低點（這根 K 棒之前已經收盤的那根）----
        six = state['six']
        six_idx = ts // SIX_H_MS
        if six['idx'] != six_idx:
            if six['idx'] is not None:
                six['prev_h'], six['prev_l'] = six['run_h'], six['run_l']
            six['idx'], six['run_h'], six['run_l'] = six_idx, h, l
        else:
            six['run_h'], six['run_l'] = max(six['run_h'], h), min(six['run_l'], l)

        # ---- 1H／4H 流動性獵取 ----
        go_long = go_short = False
        for tf, ms in HTF_MS.items():
            s = state['htf'][tf]
            idx = ts // ms
            if s['idx'] != idx:
                if s['idx'] is not None:
                    s['prev_h'], s['prev_l'] = s['run_h'], s['run_l']
                s['idx'], s['run_h'], s['run_l'], s['o'] = idx, h, l, o
                _reset(s, 's')
                _reset(s, 'l')
            else:
                s['run_h'], s['run_l'] = max(s['run_h'], h), min(s['run_l'], l)
            if s['prev_h'] is None:
                continue
            # 做空
            if h > s['prev_h']:
                s['s_sweep'] = True
            if s['s_sweep'] and l < s['o']:
                s['s_open'] = True
            if bear_fvg:
                s['s_fvg'] = True
            if bear_choch and s['s_fvg']:          # FVG 要先出現，CHoCH 才算
                s['s_choch'] = True
            if s['s_sweep'] and s['s_open'] and s['s_fvg'] and s['s_choch']:
                go_short = True
                _reset(s, 's')
            # 做多
            if l < s['prev_l']:
                s['l_sweep'] = True
            if s['l_sweep'] and h > s['o']:
                s['l_open'] = True
            if bull_fvg:
                s['l_fvg'] = True
            if bull_choch and s['l_fvg']:
                s['l_choch'] = True
            if s['l_sweep'] and s['l_open'] and s['l_fvg'] and s['l_choch']:
                go_long = True
                _reset(s, 'l')

        if go_long and six['prev_l'] is not None and six['prev_l'] < c:
            sl = six['prev_l']
            out.append(Signal(direction='long', entry_price=c, sl_price=sl, tp_price=c + (c - sl) * rr, candle_time=ts))
        elif go_short and six['prev_h'] is not None and six['prev_h'] > c:
            sl = six['prev_h']
            out.append(Signal(direction='short', entry_price=c, sl_price=sl, tp_price=c - (sl - c) * rr, candle_time=ts))

    state['buffer'] = buf
    return state, out
