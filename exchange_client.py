"""
跟 BingX 要資料的模組，用 ccxt 套件。
"""

import time
import threading
import ccxt


_markets_cache = None
_markets_loaded_at = 0.0
_markets_lock = threading.Lock()
MARKETS_TTL_SEC = 3600

# 全站共用「一個」BingX 連線物件。
# 以前每次 get_exchange() 都新建一個 ccxt 物件再塞進整份市場清單，一次掃描就建一百多個，
# 每個都要好幾 MB、又吃 CPU，Render 免費方案（512MB）因此常常記憶體爆掉重開、查幣也很慢。
# 現在只建一個大家共用（只讀公開行情，多執行緒一起用沒問題），市場清單每小時更新時才換新的。
_shared = None
_shared_lock = threading.Lock()


def _new_exchange():
    return ccxt.bingx({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',   # 永續合約
        },
    })


def _get_cached_markets():
    """BingX 的市場清單很大，載入要好幾秒。全站共用一份，每小時才重抓一次。"""
    global _markets_cache, _markets_loaded_at, _shared
    with _markets_lock:
        now = time.time()
        if _markets_cache is not None and now - _markets_loaded_at < MARKETS_TTL_SEC:
            return _markets_cache
        try:
            tmp = _new_exchange()
            tmp.load_markets()
            _markets_cache = tmp.markets
            _markets_loaded_at = now
            with _shared_lock:
                _shared = tmp          # 剛載好市場清單的這個，直接當共用連線
        except Exception:
            # 載入失敗就沿用舊的 (如果有)，沒有的話回傳 None 讓呼叫端自己處理
            pass
        return _markets_cache


def get_exchange():
    """
    回傳全站共用的 BingX 連線物件 (只讀公開資料，不需要API金鑰)。
    市場清單過期時會順便重抓並換一個新的共用物件。
    """
    global _shared
    _get_cached_markets()
    with _shared_lock:
        if _shared is None:
            _shared = _new_exchange()   # 市場清單抓不到時先給一個空的，ccxt 用到時會自己載
        return _shared


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


def get_ticker_info(exchange, symbol: str) -> dict:
    """單一幣種的最新價 + 24 小時漲跌幅(%)。抓不到的欄位是 None。"""
    t = exchange.fetch_ticker(symbol)
    return {'price': t.get('last'), 'change_24h': t.get('percentage')}
