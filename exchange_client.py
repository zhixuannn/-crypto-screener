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
