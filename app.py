"""
XUAN 3+1 + 賽克斯 BingX 訊號掃描網站 (狀態持久化版)
- XUAN 3+1：5分鐘線，CHoCH+FVG+BOS+訂單塊
- 賽克斯：15分鐘、1小時兩個時區各自獨立掃描，Vegas Channel + QQE MOD
- 兩套策略共用同一份幣種範圍 (CMC前100大 ∩ BingX永續 ∩ 排除穩定幣)
"""

import os
import time
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

import database
import exchange_client
import notifier
import cmc_client
import strategy
import sykes_strategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

TIMEFRAME = os.environ.get('SCAN_TIMEFRAME', '5m')
SCAN_INTERVAL_MINUTES = int(os.environ.get('SCAN_INTERVAL_MINUTES', '5'))
SWING_LENGTH = int(os.environ.get('SWING_LENGTH', '5'))
BOOTSTRAP_CANDLE_LIMIT = int(os.environ.get('BOOTSTRAP_CANDLE_LIMIT', '1000'))
MAX_WORKERS = int(os.environ.get('SCAN_MAX_WORKERS', '5'))
TP_RR = float(os.environ.get('TP_RR', '1.0'))

SYKES_TIMEFRAMES = ['15m', '1h']
SYKES_BOOTSTRAP_LIMIT = int(os.environ.get('SYKES_BOOTSTRAP_LIMIT', '1000'))
SYKES_RR = float(os.environ.get('SYKES_RR', '1.0'))

STABLECOIN_SYMBOLS = {
    'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'USDD',
    'USDP', 'FDUSD', 'PYUSD', 'USDE', 'FRAX', 'GUSD'
}

TW_TZ = datetime.timezone(datetime.timedelta(hours=8))

app = Flask(__name__)


def time_ago_str(ms: int, now_ms: int) -> str:
    delta_sec = max(0, (now_ms - ms) / 1000)
    if delta_sec < 60:
        return '剛剛'
    minutes = int(delta_sec / 60)
    if minutes < 60:
        return f'{minutes}分鐘前'
    hours = int(minutes / 60)
    if hours < 24:
        return f'{hours}小時前'
    days = int(hours / 24)
    return f'{days}天前'


def build_bingx_symbol_map(exchange) -> dict:
    perp_symbols =
