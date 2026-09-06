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
