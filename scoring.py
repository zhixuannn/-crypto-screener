"""
OI / CVD 資料評分 (各 0~20，XUAN 再等比例縮成各 15 分)。
規則跟「訊號資料評分試算表.xlsx」一致。可用環境變數調整：

SCORE_MIN            XUAN 的通過門檻，0~100 分 (預設 0 = 全部通過，只記錄分數)
OI_UP_BARS           近4根OI至少幾根上升才算『OI上升』 (預設 3)
OI_UNKNOWN_SCORE     OI 方向不明、或幣安沒有這個幣時的分數 (預設 0)
CVD_NODATA_SCORE     CVD 沒有資料時的分數 (預設 0)
CVD_RECENT / CVD_PRIOR  CVD 背離比較的「最近N根」與「之前N根」 (預設 10 / 20)

幣安連不上或被擋 (例如 451) 時，evaluate() 回傳 None，呼叫端『放行』訊號，不會因為抓不到資料而全部擋掉。
"""

import os
import logging

import binance_data

logger = logging.getLogger(__name__)

SCORE_MIN = int(os.environ.get('SCORE_MIN', '0'))
OI_UP_BARS = int(os.environ.get('OI_UP_BARS', '3'))
OI_UNKNOWN_SCORE = int(os.environ.get('OI_UNKNOWN_SCORE', '0'))
CVD_NODATA_SCORE = int(os.environ.get('CVD_NODATA_SCORE', '0'))
CVD_RECENT = int(os.environ.get('CVD_RECENT', '10'))
CVD_PRIOR = int(os.environ.get('CVD_PRIOR', '20'))

# (方向, 價格, OI) -> 分數
OI_TABLE = {
    ('long', '漲', '升'): 20,
    ('long', '漲', '降'): 8,
    ('long', '跌', '降'): 5,
    ('long', '跌', '升'): 0,
    ('short', '跌', '升'): 20,
    ('short', '跌', '降'): 8,
    ('short', '漲', '降'): 5,
    ('short', '漲', '升'): 0,
}

# (方向, CVD狀態) -> 分數
CVD_TABLE = {
    ('long', '看多背離'): 20,
    ('long', '無背離'): 8,
    ('long', '看空背離'): 0,
    ('short', '看空背離'): 20,
    ('short', '無背離'): 8,
    ('short', '看多背離'): 0,
}


def score_oi(direction: str, closes: list, oi_values):
    """
    價格方向：最新收盤 vs 4 根前收盤。
    OI 方向：最近 5 筆 OI 形成 4 個變化，上升根數 >= OI_UP_BARS 算升，<= 4-OI_UP_BARS 算降，其餘不明。
    回傳 (分數, 說明文字)
    """
    if oi_values is None or len(oi_values) < 5 or len(closes) < 5:
        return OI_UNKNOWN_SCORE, 'OI無資料'

    price_state = '漲' if closes[-1] > closes[-5] else '跌'
    last5 = oi_values[-5:]
    rising = sum(1 for i in range(1, 5) if last5[i] > last5[i - 1])
    if rising >= OI_UP_BARS:
        oi_state = '升'
    elif rising <= 4 - OI_UP_BARS:
        oi_state = '降'
    else:
        return OI_UNKNOWN_SCORE, f'價{price_state}·OI方向不明({rising}/4根上升)'

    score = OI_TABLE.get((direction, price_state, oi_state), 0)
    return score, f'價{price_state}·OI{oi_state}({rising}/4根上升)'


def detect_cvd_divergence(highs: list, lows: list, vols: list, buy_vols: list,
                          recent: int = None, prior: int = None) -> str:
    """
    每根 CVD 變化 = 主動買入量 - 主動賣出量 = 2*買入量 - 總量，再一路累加。
    看多背離(吸收)：最近價格創新低，但 CVD 沒有跟著創新低。
    看空背離(疲乏)：最近價格創新高，但 CVD 沒有跟著創新高。
    資料不夠回傳 '無資料'。
    """
    recent = recent or CVD_RECENT
    prior = prior or CVD_PRIOR
    need = recent + prior
    n = min(len(highs), len(lows), len(vols), len(buy_vols))
    if n < need:
        return '無資料'

    highs, lows, vols, buy_vols = highs[-need:], lows[-need:], vols[-need:], buy_vols[-need:]
    cvd = []
    total = 0.0
    for v, b in zip(vols, buy_vols):
        total += 2 * b - v
        cvd.append(total)

    p_lows, r_lows = lows[:prior], lows[prior:]
    p_highs, r_highs = highs[:prior], highs[prior:]
    p_cvd, r_cvd = cvd[:prior], cvd[prior:]

    bullish = min(r_lows) < min(p_lows) and min(r_cvd) > min(p_cvd)
    bearish = max(r_highs) > max(p_highs) and max(r_cvd) < max(p_cvd)

    if bullish and not bearish:
        return '看多背離'
    if bearish and not bullish:
        return '看空背離'
    return '無背離'


def score_cvd(direction: str, inputs: dict):
    cvd_type = detect_cvd_divergence(inputs['highs'], inputs['lows'], inputs['vols'], inputs['buy_vols'])
    if cvd_type == '無資料':
        return CVD_NODATA_SCORE, 'CVD無資料', cvd_type
    return CVD_TABLE.get((direction, cvd_type), 0), cvd_type, cvd_type


def score_from_inputs(direction: str, inputs):
    """inputs 為 None 代表幣安沒有這個幣：兩項都算無資料。"""
    if inputs is None:
        oi_score, oi_note = OI_UNKNOWN_SCORE, 'OI無資料'
        cvd_score, cvd_note = CVD_NODATA_SCORE, 'CVD無資料'
    else:
        oi_score, oi_note = score_oi(direction, inputs['closes'], inputs['oi'])
        cvd_score, cvd_note, _ = score_cvd(direction, inputs)
    return {
        'oi_score': oi_score,
        'cvd_score': cvd_score,
        'total': oi_score + cvd_score,
        'note': f'{oi_note} | {cvd_note}',
        'max': 40,
        'detail': [
            {'k': 'oi', 'l': 'OI', 's': oi_score, 'm': 20, 'n': oi_note},
            {'k': 'cvd', 'l': 'CVD', 's': cvd_score, 'm': 20, 'n': cvd_note},
        ],
        'warning': None,
    }


def evaluate(base_symbol: str, direction: str, timeframe: str):
    """
    對一個訊號打分數。
    回傳 dict(oi_score, cvd_score, total, note)；
    幣安連不上/被擋 -> 回傳 None (呼叫端應放行，且不記錄分數)。
    """
    try:
        inputs = binance_data.fetch_inputs(base_symbol, timeframe)
    except binance_data.DataSourceUnavailable as e:
        logger.warning(f'[評分] 幣安資料不可用，{base_symbol} 的訊號放行且不計分: {e}')
        return None
    except Exception as e:
        logger.warning(f'[評分] {base_symbol} 計分發生錯誤，訊號放行且不計分: {e}')
        return None
    return score_from_inputs(direction, inputs)
