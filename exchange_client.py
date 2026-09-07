"""
跟 BingX 要資料的模組，用 ccxt 套件。
"""

import time
import ccxt


def get_exchange():
    """建立 BingX 交易所連線物件 (只讀公開資料，不需要API金鑰)。"""
    exchange = ccxt.bingx({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',   # 永續合約
        },
    })
    return exchange


def get_perpetual_symbols(exchange) -> list:
    """回傳 BingX 上所有 USDT 本位永續合約的交易對代號。"""
    markets = exchange.load_markets()
    symbols = []
    for symbol, market in markets.items():
        if not market.get('active', True):
            continue
        if market.get('swap') and market.get('quote') == 'USDT':
            symbols.append(symbol)
    return sorted(symbols)


def fetch_closed_candles(exchange, symbol: str, timeframe: str = '5m', limit: int = 500) -> list:
    """
    抓取指定交易對的K線，並把「還在跑、還沒收盤」的最後一根濾掉。
    回傳格式: [[timestamp_ms, open, high, low, close, volume], ...]，由舊到新排序。
    """
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        return []

    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    now_ms = int(time.time() * 1000)

    # 如果最後一根的「收盤時間」還沒到，代表它還在跑，濾掉
    last_candle = raw[-1]
    if last_candle[0] + timeframe_ms > now_ms:
        raw = raw[:-1]

    return raw




def fetch_new_closed_candles(exchange, symbol: str, timeframe: str = '5m', since_ms: int = None, limit: int = 1000) -> list:
    """
    抓取『從 since_ms 之後』新出現、且已經收盤的K棒(不含 since_ms 那一根本身，避免重複)。
    如果 since_ms 是 None，等同呼叫 fetch_closed_candles()。
    如果中間漏接很久，會自動分批一路抓到追上最新為止。
    """
    if since_ms is None:
        return fetch_closed_candles(exchange, symbol, timeframe, limit)

    all_new = []
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    fetch_since = since_ms + 1
    now_ms = int(time.time() * 1000)

    while True:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=fetch_since, limit=limit)
        if not raw:
            break
        last_candle = raw[-1]
        if last_candle[0] + timeframe_ms > now_ms:
            raw = raw[:-1]
        if not raw:
            break
        all_new.extend(raw)
        fetch_since = raw[-1][0] + 1
        if len(raw) < limit:
            break

    return all_new




def get_last_prices(exchange, symbols: list) -> dict:
    """
    一次抓一批交易對的最新成交價，回傳 {symbol: last_price}。
    用 fetch_tickers 一次要多個，比逐一呼叫快很多。
    """
    if not symbols:
        return {}
    try:
        tickers = exchange.fetch_tickers(symbols)
    except Exception:
        try:
            tickers = exchange.fetch_tickers()
        except Exception:
            return {}
    result = {}
    for sym, t in tickers.items():
        last = t.get('last')
        if last is not None:
            result[sym] = last
    return result
