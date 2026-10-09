"""
幣安合約公開資料模組 (不需要 API Key，只讀資料)。
提供給 scoring.py 計算「OI 分數」和「CVD 背離分數」用：
- K線：含「主動買入量」，用來算 CVD (買入量 - 賣出量 的累計)
- OI 歷史：未平倉量的歷史資料

重要：幣安合約會擋部分國家 (例如美國) 的 IP，回傳 451。
遇到被擋或連不上時，會丟出 DataSourceUnavailable，並暫停一段時間不再重試，避免拖慢掃描。
"""

import os
import time
import logging
import threading
import requests

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get('BINANCE_FAPI_BASE', 'https://fapi.binance.com')
TIMEOUT = 10
BLOCK_COOLDOWN_SEC = int(os.environ.get('BINANCE_BLOCK_COOLDOWN_SEC', '600'))
KLINE_LIMIT = 60

# 幣安 OI 歷史只支援這些週期
OI_PERIODS = {'5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'}

_lock = threading.Lock()
_blocked_until = 0.0
_blocked_reason = ''
_symbol_cache = {}   # base -> (binance_symbol or None, cached_at)
SYMBOL_CACHE_SEC = 6 * 3600


class DataSourceUnavailable(Exception):
    """幣安連不上或被擋 (例如 451)。呼叫端應該『放行』而不是擋掉訊號。"""


class SymbolNotFound(Exception):
    """這個幣在幣安合約沒有 (或名稱對不上)。"""


def _get(path: str, params: dict):
    global _blocked_until, _blocked_reason
    now = time.time()
    with _lock:
        if now < _blocked_until:
            raise DataSourceUnavailable(f'暫停中: {_blocked_reason}')
    try:
        resp = requests.get(BASE_URL + path, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        with _lock:
            _blocked_until = time.time() + 60
            _blocked_reason = f'連線失敗 {type(e).__name__}'
        raise DataSourceUnavailable(_blocked_reason)

    if resp.status_code in (451, 403):
        with _lock:
            _blocked_until = time.time() + BLOCK_COOLDOWN_SEC
            _blocked_reason = f'HTTP {resp.status_code} (這個 IP 可能被幣安擋住)'
        logger.warning(f'[幣安] {_blocked_reason}，暫停 {BLOCK_COOLDOWN_SEC} 秒')
        raise DataSourceUnavailable(_blocked_reason)
    if resp.status_code == 429 or resp.status_code == 418:
        with _lock:
            _blocked_until = time.time() + 60
            _blocked_reason = f'HTTP {resp.status_code} (被限速)'
        raise DataSourceUnavailable(_blocked_reason)
    if resp.status_code == 400:
        raise SymbolNotFound(resp.text[:100])
    if resp.status_code != 200:
        raise DataSourceUnavailable(f'HTTP {resp.status_code}')
    return resp.json()


def ping() -> dict:
    """回傳目前連線狀態，給網站的檢查頁用。"""
    try:
        r = requests.get(BASE_URL + '/fapi/v1/ping', timeout=TIMEOUT)
        return {'ok': r.status_code == 200, 'status_code': r.status_code}
    except requests.RequestException as e:
        return {'ok': False, 'status_code': None, 'error': type(e).__name__}


def resolve_symbol(base: str):
    """BingX 的 BTC 對應幣安 BTCUSDT；有些小幣幣安叫 1000XXXUSDT。找不到回傳 None。"""
    base = base.upper()
    now = time.time()
    cached = _symbol_cache.get(base)
    if cached and now - cached[1] < SYMBOL_CACHE_SEC:
        return cached[0]

    found = None
    for cand in (base + 'USDT', '1000' + base + 'USDT'):
        try:
            _get('/fapi/v1/klines', {'symbol': cand, 'interval': '1m', 'limit': 1})
            found = cand
            break
        except SymbolNotFound:
            continue
    _symbol_cache[base] = (found, now)
    return found


def fetch_inputs(base: str, timeframe: str):
    """
    抓計算分數需要的原始資料。
    回傳 dict: closes/highs/lows/vols/buy_vols (已收盤K棒，由舊到新)、oi (OI 數值，由舊到新，可能為 None)
    幣安沒有這個幣 -> 回傳 None。連不上/被擋 -> 丟 DataSourceUnavailable。
    """
    sym = resolve_symbol(base)
    if sym is None:
        return None

    try:
        klines = _get('/fapi/v1/klines', {'symbol': sym, 'interval': timeframe, 'limit': KLINE_LIMIT})
    except SymbolNotFound:
        return None

    now_ms = int(time.time() * 1000)
    if klines and klines[-1][6] > now_ms:   # 第 7 欄是收盤時間，還沒到代表這根還在跑
        klines = klines[:-1]
    if not klines:
        return None

    oi_values = None
    if timeframe in OI_PERIODS:
        try:
            oi_rows = _get('/futures/data/openInterestHist', {'symbol': sym, 'period': timeframe, 'limit': 10})
            oi_values = [float(r['sumOpenInterest']) for r in oi_rows]
        except SymbolNotFound:
            oi_values = None

    return {
        'binance_symbol': sym,
        'closes': [float(k[4]) for k in klines],
        'highs': [float(k[2]) for k in klines],
        'lows': [float(k[3]) for k in klines],
        'vols': [float(k[5]) for k in klines],
        'buy_vols': [float(k[9]) for k in klines],   # 主動買入量
        'oi': oi_values,
    }
