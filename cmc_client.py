"""
跟 CoinMarketCap 要「市值前100大」幣種名單的模組。
- 每天最多真正呼叫一次 API，其餘時間都用記憶體裡的快取，節省額度
- 回傳的是幣種代號 (例如 'BTC'、'ETH')，不含交易所或交易對格式
"""

import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

CMC_API_KEY = os.environ.get('CMC_API_KEY', '')
CMC_URL = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
TOP_N = 100
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24小時

_cache_symbols = []
_cache_time = 0


def get_top100_symbols(force_refresh: bool = False) -> list:
    """
    回傳市值前100大幣種代號清單 (例如 ['BTC', 'ETH', 'SOL', ...])。
    24小時內重複呼叫會直接回傳快取，不會真的打API。
    """
    global _cache_symbols, _cache_time

    now = time.time()
    cache_is_fresh = (now - _cache_time) < CACHE_TTL_SECONDS

    if cache_is_fresh and not force_refresh and _cache_symbols:
        return _cache_symbols

    if not CMC_API_KEY:
        logger.error('CMC_API_KEY 未設定，無法取得前100大名單')
        return _cache_symbols

    try:
        headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
        params = {'start': 1, 'limit': TOP_N, 'sort': 'market_cap', 'convert': 'USD'}
        resp = requests.get(CMC_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        symbols = [item['symbol'] for item in data.get('data', [])]
        if symbols:
            _cache_symbols = symbols
            _cache_time = now
            logger.info(f'已更新CMC前{TOP_N}大名單，共 {len(symbols)} 個幣種')
        return _cache_symbols
    except Exception as e:
        logger.warning(f'取得CMC前100大名單失敗: {e}，使用舊快取')
        return _cache_symbols
