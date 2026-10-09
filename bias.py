"""
偏見 (K1/K2/K3 四種情況) 與時段判斷。

偏見：用最近兩根「已收盤」K棒 (K1=兩根前、K2=前一根)，推測現在這根 (K3) 偏多還是偏空：
  偏多 = (K1陽線 且 K2收盤站上K1高點) 或 (K1陰線 且 K2收盤沒跌破K1低點)
  偏空 = (K1陰線 且 K2收盤跌破K1低點) 或 (K1陽線 且 K2收盤沒站上K1高點)
  K1 是十字線 (收盤=開盤) 時不判斷，回傳 None。
"""

import datetime

TW_TZ = datetime.timezone(datetime.timedelta(hours=8))


def bias_direction(candles: list):
    """candles 為已收盤K棒 (由舊到新)，回傳 'long' / 'short' / None。"""
    if not candles or len(candles) < 2:
        return None
    k1, k2 = candles[-2], candles[-1]
    k1_open, k1_high, k1_low, k1_close = k1[1], k1[2], k1[3], k1[4]
    k2_close = k2[4]

    k1_bull = k1_close > k1_open
    k1_bear = k1_close < k1_open
    break_high = k2_close > k1_high
    break_low = k2_close < k1_low

    long_setup = (k1_bull and break_high) or (k1_bear and not break_low)
    short_setup = (k1_bear and break_low) or (k1_bull and not break_high)
    if long_setup:
        return 'long'
    if short_setup:
        return 'short'
    return None


def tw_hour(ts_ms: int) -> int:
    """毫秒時間戳 -> 台灣時間的『幾點』(0~23)。"""
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=TW_TZ).hour


def day_session(hour: int):
    """
    日內時段 (台灣時間)：
      A段 8-12、M段 12-16、D段 16-24、其餘 0-8 = 'N' (不給分)
    回傳 (代號, 中文)。
    """
    if 8 <= hour < 12:
        return 'A', 'A段'
    if 12 <= hour < 16:
        return 'M', 'M段'
    if 16 <= hour < 24:
        return 'D', 'D段'
    return 'N', '夜間'


def hour_in_4h(hour: int) -> int:
    """4H K棒 (0,4,8,12,16,20 點開盤) 內的第幾個小時，1~4。"""
    return hour % 4 + 1
