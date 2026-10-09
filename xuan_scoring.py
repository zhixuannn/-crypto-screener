"""
XUAN 3+1 專用的 100 分評分 (結構 70 + 數據 30)。

分項 (每一項都會分開記錄，之後可以在統計頁驗證哪一項真的有用)：
  日線偏見 15 | 4H偏見 10 | 1H偏見 5      -> 順勢才給分，逆勢 0 分
  15分結構 15 | 5分結構 10                -> BOS/CHoCH方向 60% + 高低點排列 40%
  日內時段 8  | 4H內時段 7               -> D段(16-24)8、M段(12-16)5、A段(8-12)3、夜間0；4H第2、3小時 7
  OI 15 | CVD 15                          -> 由 scoring.py 的 0~20 分等比例縮成 0~15

警告 (不擋訊號，只標記)：
  1. 訊號落在 4H K棒的第 4 個小時 (回調段)
  2. 日線偏見跟訊號方向相反 (逆勢)

資料抓不到 (BingX K線或幣安) 時：該項給 0 分並標註『無資料』，
而且整筆訊號直接放行 (incomplete=True)，避免抓不到資料就把訊號全擋掉。

結構：
  gather(symbol, tf)   -> 『同時』去抓 5 組 K 線 + 幣安 OI/CVD 資料 (比一個一個抓快很多)
  score(inputs, direction, candle_time_ms) -> 純計算，不連網路
  evaluate_xuan(...)   = gather + score  (訊號打分用)
  查幣功能：gather 一次，做多、做空各 score 一次，只花一次抓資料的時間
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import exchange_client
import scoring
import bias
import smc_structure
import binance_data

logger = logging.getLogger(__name__)

W_BIAS_DAY, W_BIAS_4H, W_BIAS_1H = 15, 10, 5
W_STRUCT_15M, W_STRUCT_5M = 15, 10
W_SESSION_DAY, W_SESSION_4H = 8, 7
W_OI, W_CVD = 15, 15
MAX_TOTAL = (W_BIAS_DAY + W_BIAS_4H + W_BIAS_1H + W_STRUCT_15M + W_STRUCT_5M +
             W_SESSION_DAY + W_SESSION_4H + W_OI + W_CVD)   # = 100

DAY_SESSION_POINTS = {'D': 8, 'M': 5, 'A': 3, 'N': 0}

# 方便測試時替換
fetch_closed = exchange_client.fetch_closed_candles
fetch_binance = binance_data.fetch_inputs

_CANDLE_JOBS = (('1d', 6), ('4h', 6), ('1h', 6), ('15m', 300), ('5m', 300))


def _item(key, label, score, max_points, note):
    return {'k': key, 'l': label, 's': score, 'm': max_points, 'n': note}


def gather(symbol: str, signal_timeframe: str = '5m') -> dict:
    """
    同時抓齊評分需要的所有資料。回傳：
      {'candles': {'1d': [...]|None, ...}, 'binance': inputs|None, 'binance_ok': bool, 'incomplete': bool}
    抓不到的項目是 None，並把 incomplete 設 True。
    """
    base = symbol.split('/')[0]

    def job_candles(tf, limit):
        try:
            ex = exchange_client.get_exchange()   # 每個執行緒自己一個連線物件，但共用市場清單快取
            return fetch_closed(ex, symbol, tf, limit)
        except Exception as e:
            logger.warning(f'[XUAN評分] 抓 {symbol} {tf} K線失敗: {e}')
            return None

    def job_binance():
        try:
            return ('ok', fetch_binance(base, signal_timeframe))
        except binance_data.DataSourceUnavailable as e:
            logger.warning(f'[XUAN評分] 幣安資料不可用 ({base}): {e}')
            return ('down', None)
        except Exception as e:
            logger.warning(f'[XUAN評分] {base} 幣安資料錯誤: {e}')
            return ('down', None)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {tf: pool.submit(job_candles, tf, lim) for tf, lim in _CANDLE_JOBS}
        fb = pool.submit(job_binance)
        candles = {tf: f.result() for tf, f in futs.items()}
        b_state, b_inputs = fb.result()

    incomplete = any(v is None for v in candles.values()) or b_state == 'down'
    return {'candles': candles, 'binance': b_inputs, 'binance_ok': b_state == 'ok', 'incomplete': incomplete}


def score(inputs: dict, direction: str, candle_time_ms: int) -> dict:
    """用 gather() 抓好的資料算出 100 分。回傳 dict：
      total / max / oi_score / cvd_score / detail(list) / note / warning / incomplete / daily_bias
    """
    candles = inputs['candles']
    incomplete = inputs['incomplete']
    items = []
    daily_bias = None

    # ---- 偏見 (日 / 4H / 1H) ----
    for tf, key, label, weight in (('1d', 'bias_d', '日線偏見', W_BIAS_DAY),
                                   ('4h', 'bias_4h', '4H偏見', W_BIAS_4H),
                                   ('1h', 'bias_1h', '1H偏見', W_BIAS_1H)):
        c = candles.get(tf)
        if c is None or len(c) < 2:
            items.append(_item(key, label, 0, weight, '無資料'))
            continue
        b = bias.bias_direction(c)
        if key == 'bias_d':
            daily_bias = b
        if b is None:
            items.append(_item(key, label, 0, weight, '無偏見'))
        elif b == direction:
            items.append(_item(key, label, weight, weight, '順勢'))
        else:
            items.append(_item(key, label, 0, weight, '逆勢'))

    # ---- 結構 (15m / 5m) ----
    for tf, key, label, weight in (('15m', 'st_15m', '15分結構', W_STRUCT_15M),
                                   ('5m', 'st_5m', '5分結構', W_STRUCT_5M)):
        c = candles.get(tf)
        res = smc_structure.score_structure(direction, c, weight) if c else None
        if res is None:
            items.append(_item(key, label, 0, weight, '無資料'))
        else:
            items.append(_item(key, label, res[0], weight, res[1]))

    # ---- 時段 ----
    hour = bias.tw_hour(candle_time_ms)
    sess_code, sess_label = bias.day_session(hour)
    items.append(_item('sess_day', '日內時段', DAY_SESSION_POINTS[sess_code], W_SESSION_DAY, sess_label))
    h4 = bias.hour_in_4h(hour)
    items.append(_item('sess_4h', '4H內時段', W_SESSION_4H if h4 in (2, 3) else 0, W_SESSION_4H, f'第{h4}小時'))

    # ---- 數據 (OI / CVD) ----
    if not inputs.get('binance_ok'):
        oi_pts = cvd_pts = 0
        items.append(_item('oi', 'OI', 0, W_OI, '無資料'))
        items.append(_item('cvd', 'CVD', 0, W_CVD, '無資料'))
    else:
        raw = scoring.score_from_inputs(direction, inputs['binance'])
        oi_pts = round(raw['oi_score'] * W_OI / 20)
        cvd_pts = round(raw['cvd_score'] * W_CVD / 20)
        oi_note, _, cvd_note = raw['note'].partition(' | ')
        items.append(_item('oi', 'OI', oi_pts, W_OI, oi_note))
        items.append(_item('cvd', 'CVD', cvd_pts, W_CVD, cvd_note))

    total = sum(i['s'] for i in items)

    # ---- 警告 ----
    reasons = []
    if h4 == 4:
        reasons.append('訊號在 4H 最後 1 小時 (回調段)')
    if daily_bias is not None and daily_bias != direction:
        reasons.append('日線偏見逆勢')
    warning = '；'.join(reasons) if reasons else None

    note = ' ｜ '.join(f"{i['l']}{i['s']}/{i['m']}({i['n']})" for i in items)
    return {
        'total': total,
        'max': MAX_TOTAL,
        'oi_score': oi_pts,
        'cvd_score': cvd_pts,
        'detail': items,
        'note': note,
        'warning': warning,
        'incomplete': incomplete,
        'daily_bias': daily_bias,
    }


def evaluate_xuan(symbol: str, direction: str, candle_time_ms: int, signal_timeframe: str = '5m') -> dict:
    """symbol 例如 'BTC/USDT:USDT'。"""
    return score(gather(symbol, signal_timeframe), direction, candle_time_ms)
