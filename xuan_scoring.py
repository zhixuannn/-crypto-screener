"""
XUAN 3+1 專用的 100 分評分（只看結構和時段，數據面 OI/CVD 已拿掉）。

分項（每一項都會分開記錄，之後可以在紙上驗證裡看哪一項真的有用）：
  日線偏見 20 | 4H偏見 15                 -> 順勢才給分，逆勢 0 分
  15分結構 15 | 5分結構 10                -> BOS/CHoCH方向 60% + 高低點排列 40%
  偏見未完成 15                            -> 做多：今天還沒碰到昨天高點；做空：還沒碰到昨天低點
  4H流動性獵取 10                          -> 做多：這根(或上一根)4H 刺破前一根 4H 低點又收回；做空反過來
  4H內時段 10                              -> 第3小時10、第1小時5、第2小時3、第4小時0
  日內時段 5                               -> 8-12點5、12-16點3、16-24點2、0-8點0（台灣時間）

這版分數是依使用者超人交易紀錄 61 筆的實際結果調整的（2026-11）。

警告（不擋訊號，只標記）：
  1. 訊號落在 4H K棒的第 4 個小時（回調段）
  2. 日線偏見跟訊號方向相反（逆勢）
  3. 偏見已完成（已經碰到昨天高／低點）

資料抓不到（BingX K線）時：該項給 0 分並標註『無資料』，整筆訊號照樣放行 (incomplete=True)。

結構：
  gather(symbol, tf)   -> 『同時』去抓 5 組 K 線
  score(inputs, direction, candle_time_ms) -> 純計算，不連網路
  evaluate_xuan(...)   = gather + score  (訊號打分用)
  查幣功能：gather 一次，做多、做空各 score 一次
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import exchange_client
import bias
import smc_structure

logger = logging.getLogger(__name__)

W_BIAS_DAY, W_BIAS_4H = 20, 15
W_STRUCT_15M, W_STRUCT_5M = 15, 10
W_PENDING = 15
W_SWEEP_4H = 10
W_SESSION_4H, W_SESSION_DAY = 10, 5
MAX_TOTAL = (W_BIAS_DAY + W_BIAS_4H + W_STRUCT_15M + W_STRUCT_5M + W_PENDING + W_SWEEP_4H +
             W_SESSION_4H + W_SESSION_DAY)   # = 100

DAY_SESSION_POINTS = {'A': 5, 'M': 3, 'D': 2, 'N': 0}
H4_SESSION_POINTS = {3: 10, 1: 5, 2: 3, 4: 0}

DAY_MS = 86_400_000
H4_MS = 14_400_000

# 方便測試時替換
fetch_closed = exchange_client.fetch_closed_candles

_CANDLE_JOBS = (('1d', 6), ('4h', 6), ('1h', 6), ('15m', 300), ('5m', 300))


def _item(key, label, score, max_points, note):
    return {'k': key, 'l': label, 's': score, 'm': max_points, 'n': note}


def gather(symbol: str, signal_timeframe: str = '5m') -> dict:
    """
    同時抓齊評分需要的 K 線。回傳：
      {'candles': {'1d': [...]|None, ...}, 'incomplete': bool}
    抓不到的項目是 None，並把 incomplete 設 True。
    """
    def job_candles(tf, limit):
        try:
            ex = exchange_client.get_exchange()   # 每個執行緒自己一個連線物件，但共用市場清單快取
            return fetch_closed(ex, symbol, tf, limit)
        except Exception as e:
            logger.warning(f'[XUAN評分] 抓 {symbol} {tf} K線失敗: {e}')
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {tf: pool.submit(job_candles, tf, lim) for tf, lim in _CANDLE_JOBS}
        candles = {tf: f.result() for tf, f in futs.items()}

    incomplete = any(v is None for v in candles.values())
    return {'candles': candles, 'incomplete': incomplete}


def bias_progress(candles: dict, direction: str, signal_ms: int):
    """
    偏見完成了沒：比較『今天到訊號為止的最高／最低』和『昨天的最高／最低』。
    今天＝BingX 日K（UTC 0 點＝台灣早上 8 點開盤）。
    回傳 (done: True/False/None, 說明文字)。
    """
    c1d, c15 = candles.get('1d'), candles.get('15m')
    if not c1d or not c15:
        return None, '無資料'
    day_open = signal_ms // DAY_MS * DAY_MS
    prev = [c for c in c1d if c[0] < day_open]
    if not prev:
        return None, '無資料'
    prev_high, prev_low = prev[-1][2], prev[-1][3]
    today = [c for c in c15 if day_open <= c[0] <= signal_ms]
    if not today:
        return False, '今天剛開盤'
    hi, lo = max(c[2] for c in today), min(c[3] for c in today)
    if direction == 'long':
        return (hi >= prev_high), ('已碰到昨天高點' if hi >= prev_high else '還沒碰到昨天高點')
    return (lo <= prev_low), ('已碰到昨天低點' if lo <= prev_low else '還沒碰到昨天低點')


def sweep_4h(candles: dict, direction: str, signal_ms: int):
    """
    4H 流動性獵取：刺破前一根 4H 的低點（做多）／高點（做空）又收回來。
    看兩種情況，有一種成立就算：
      1. 訊號所在這根 4H（到訊號為止，用 5 分 K 拼出來）刺破上一根 4H，而且訊號收盤已經收回
      2. 上一根已收盤的 4H 刺破它前一根，並且收盤收回
    回傳 (hit: True/False/None, 說明文字)。
    """
    c4, c5 = candles.get('4h'), candles.get('5m')
    if not c4 or not c5:
        return None, '無資料'
    cur_open = signal_ms // H4_MS * H4_MS
    closed = [c for c in c4 if c[0] < cur_open]
    if not closed:
        return None, '無資料'
    prev = closed[-1]
    cur = [c for c in c5 if cur_open <= c[0] <= signal_ms]
    if cur:
        hi, lo, close = max(c[2] for c in cur), min(c[3] for c in cur), cur[-1][4]
        if direction == 'long' and lo < prev[3] and close > prev[3]:
            return True, '這根4H掃前低後收回'
        if direction == 'short' and hi > prev[2] and close < prev[2]:
            return True, '這根4H掃前高後收回'
    if len(closed) >= 2:
        a, b = closed[-2], closed[-1]
        if direction == 'long' and b[3] < a[3] and b[4] > a[3]:
            return True, '上一根4H掃前低後收回'
        if direction == 'short' and b[2] > a[2] and b[4] < a[2]:
            return True, '上一根4H掃前高後收回'
    return False, '沒有掃流動性'


def score(inputs: dict, direction: str, candle_time_ms: int) -> dict:
    """用 gather() 抓好的資料算出 100 分。回傳 dict：
      total / max / oi_score / cvd_score(固定0，相容舊欄位) / detail(list) / note / warning / incomplete / daily_bias
    """
    candles = inputs['candles']
    incomplete = inputs['incomplete']
    items = []
    daily_bias = None

    # ---- 偏見 (日 / 4H) ----
    for tf, key, label, weight in (('1d', 'bias_d', '日線偏見', W_BIAS_DAY),
                                   ('4h', 'bias_4h', '4H偏見', W_BIAS_4H)):
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

    # ---- 偏見完成了沒 ----
    done, done_note = bias_progress(candles, direction, candle_time_ms)
    items.append(_item('bias_pending', '偏見未完成', W_PENDING if done is False else 0, W_PENDING, done_note))

    # ---- 結構 (15m / 5m) ----
    for tf, key, label, weight in (('15m', 'st_15m', '15分結構', W_STRUCT_15M),
                                   ('5m', 'st_5m', '5分結構', W_STRUCT_5M)):
        c = candles.get(tf)
        res = smc_structure.score_structure(direction, c, weight) if c else None
        if res is None:
            items.append(_item(key, label, 0, weight, '無資料'))
        else:
            items.append(_item(key, label, res[0], weight, res[1]))

    # ---- 4H 流動性獵取 ----
    hit, sweep_note = sweep_4h(candles, direction, candle_time_ms)
    items.append(_item('liq_4h', '4H流動性獵取', W_SWEEP_4H if hit else 0, W_SWEEP_4H, sweep_note))

    # ---- 時段 ----
    hour = bias.tw_hour(candle_time_ms)
    h4 = bias.hour_in_4h(hour)
    items.append(_item('sess_4h', '4H內時段', H4_SESSION_POINTS.get(h4, 0), W_SESSION_4H, f'第{h4}小時'))
    sess_code, sess_label = bias.day_session(hour)
    items.append(_item('sess_day', '日內時段', DAY_SESSION_POINTS[sess_code], W_SESSION_DAY, sess_label))

    total = sum(i['s'] for i in items)

    # ---- 警告 ----
    reasons = []
    if h4 == 4:
        reasons.append('訊號在 4H 最後 1 小時 (回調段)')
    if daily_bias is not None and daily_bias != direction:
        reasons.append('日線偏見逆勢')
    if done:
        reasons.append('偏見已完成 (' + done_note + ')')
    warning = '；'.join(reasons) if reasons else None

    note = ' ｜ '.join(f"{i['l']}{i['s']}/{i['m']}({i['n']})" for i in items)
    return {
        'total': total,
        'max': MAX_TOTAL,
        'oi_score': 0,
        'cvd_score': 0,
        'detail': items,
        'note': note,
        'warning': warning,
        'incomplete': incomplete,
        'daily_bias': daily_bias,
        'bias_done': done,
        'sweep_4h': hit,
    }


def evaluate_xuan(symbol: str, direction: str, candle_time_ms: int, signal_timeframe: str = '5m') -> dict:
    """symbol 例如 'BTC/USDT:USDT'。"""
    return score(gather(symbol, signal_timeframe), direction, candle_time_ms)
