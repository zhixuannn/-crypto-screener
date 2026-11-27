"""
盤面紀錄：訊號出現時把「當下的盤面」存起來，之後在網站點開那筆訊號就看得到。

存的東西（放在 signals.snapshot，JSON）：
  before : 訊號那根（含）往前 60 根 K 棒   [[時間, 開, 高, 低, 收], ...]
  after  : 單子結束時補存：訊號之後到出場的 K 棒（最多 150 根）
  data   : 當下數據 — 價格、24h 漲跌%、24h 成交額(USDT)、資金費率、持倉量 OI(USDT)、標記價格
           （多空比 BingX 沒有提供，所以沒有）
都在背景抓，抓不到就留空，不會影響訊號本身。
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import bias
import database
import exchange_client

logger = logging.getLogger(__name__)

BINGX = 'https://open-api.bingx.com'
BEFORE_BARS = 60
AFTER_MAX_BARS = 150
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='snapshot')

TF_MS = {'1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
         '1h': 3_600_000, '2h': 7_200_000, '4h': 14_400_000, '1d': 86_400_000}


def _bingx_symbol(symbol: str) -> str:
    # 'BTC/USDT:USDT' -> 'BTC-USDT'
    base, rest = symbol.split('/', 1)
    quote = rest.split(':')[0]
    return f'{base}-{quote}'


def _get(path, sym):
    r = requests.get(BINGX + path, params={'symbol': sym}, timeout=10)
    j = r.json()
    if j.get('code') != 0:
        raise RuntimeError(j.get('msg') or str(j)[:120])
    return j.get('data') or {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def market_data(symbol: str) -> dict:
    sym = _bingx_symbol(symbol)
    out = {}
    for path, fn in (
        ('/openApi/swap/v2/quote/ticker', lambda d: {'price': _num(d.get('lastPrice')), 'change_24h': _num(d.get('priceChangePercent')),
                                                     'quote_volume_24h': _num(d.get('quoteVolume'))}),
        ('/openApi/swap/v2/quote/premiumIndex', lambda d: {'funding_rate': _num(d.get('lastFundingRate')), 'mark_price': _num(d.get('markPrice'))}),
        ('/openApi/swap/v2/quote/openInterest', lambda d: {'open_interest': _num(d.get('openInterest'))}),
    ):
        try:
            out.update(fn(_get(path, sym)))
        except Exception as e:
            logger.info(f'[盤面] {symbol} {path.rsplit("/", 1)[-1]} 抓不到: {e}')
    return out


def _candles(symbol: str, tf: str, since_ms: int, until_ms: int, limit: int) -> list:
    ex = exchange_client.get_exchange()
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, since=since_ms, limit=limit) or []
    return [[int(c[0]), c[1], c[2], c[3], c[4]] for c in raw if since_ms <= c[0] <= until_ms]


LIGHT_MS = {'15m': 900_000, '30m': 1_800_000, '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000}


def compute_lights(symbol: str, ref_ms: int, tfs=None) -> dict:
    """
    偏見紅綠燈（跟 TradingView 指標同一套）：每個時區用自己「已收盤」的最後兩根 K 棒判斷
    1 = 多（綠燈）、-1 = 空（紅燈）。K1 是十字線判斷不出來時，往前找上一次的燈號（沿用）。
    ref_ms = 訊號那根 K 棒收盤的時間；抓不到資料的時區記 None。日線用 UTC 0 點 = 台灣早上 8 點開盤。
    """
    ex = exchange_client.get_exchange()
    out = {}
    for tf, ms in LIGHT_MS.items():
        if tfs and tf not in tfs:
            continue
        try:
            raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=40) or []
            closed = [c for c in raw if c[0] + ms <= ref_ms]
            d = None
            for j in range(len(closed), 1, -1):
                d = bias.bias_direction(closed[:j])
                if d:
                    break
            out[tf] = 1 if d == 'long' else -1 if d == 'short' else 0
        except Exception as e:
            logger.info(f'[紅綠燈] {symbol} {tf} 抓不到: {e}')
            out[tf] = None
    return out


def _capture_entry(signal_id: int, symbol: str, tf: str, candle_time: int):
    step0 = TF_MS.get(tf, 300_000)
    try:
        database.set_lights(signal_id, compute_lights(symbol, candle_time + step0))
    except Exception as e:
        logger.warning(f'[紅綠燈] {symbol} 紀錄失敗: {e}')
    snap = {'tf': tf, 'taken_at': int(time.time() * 1000)}
    step = TF_MS.get(tf, 300_000)
    try:
        snap['before'] = _candles(symbol, tf, candle_time - (BEFORE_BARS - 1) * step, candle_time, BEFORE_BARS + 5)
    except Exception as e:
        logger.warning(f'[盤面] {symbol} {tf} K 線抓不到: {e}')
    snap['data'] = market_data(symbol)
    database.set_snapshot(signal_id, snap)


def _capture_exit(signal_id: int, symbol: str, tf: str, candle_time: int, closed_at: int):
    step = TF_MS.get(tf, 300_000)
    try:
        after = _candles(symbol, tf, candle_time + step, closed_at, AFTER_MAX_BARS)
    except Exception as e:
        logger.warning(f'[盤面] {symbol} {tf} 出場 K 線抓不到: {e}')
        return
    database.set_snapshot(signal_id, {'after': after, 'closed_at': closed_at})


def capture_entry(signal_id, symbol, tf, candle_time):
    if signal_id:
        _pool.submit(_safe, _capture_entry, signal_id, symbol, tf or '5m', candle_time)


def capture_exit(signal_id, symbol, tf, candle_time, closed_at):
    if signal_id:
        _pool.submit(_safe, _capture_exit, signal_id, symbol, tf or '5m', candle_time, closed_at)


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception as e:
        logger.warning(f'[盤面] 紀錄失敗: {e}')
