"""
XUAN 3+1 BingX 訊號掃描網站
- 每 SCAN_INTERVAL_MINUTES 分鐘，自動掃描 BingX 上所有 USDT 永續合約
- 用 XUAN 3+1 邏輯 (strategy.py) 判斷每個幣種最新一根K棒有沒有觸發進場訊號
- 有新訊號就存進資料庫，並發送 Telegram 通知
- 網頁首頁顯示最近的訊號列表
"""

import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler

import database
import exchange_client
import notifier
from strategy import get_latest_signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

TIMEFRAME = os.environ.get('SCAN_TIMEFRAME', '5m')
SCAN_INTERVAL_MINUTES = int(os.environ.get('SCAN_INTERVAL_MINUTES', '5'))
SWING_LENGTH = int(os.environ.get('SWING_LENGTH', '5'))
CANDLE_LIMIT = int(os.environ.get('CANDLE_LIMIT', '500'))
MAX_WORKERS = int(os.environ.get('SCAN_MAX_WORKERS', '5'))
TP_RR = float(os.environ.get('TP_RR', '1.0'))   # 止盈盈虧比，預設1:1

app = Flask(__name__)


def scan_one_symbol(symbol: str):
    """對單一幣種抓資料並判斷訊號，回傳 (symbol, Signal or None)。失敗回傳 (symbol, None)。"""
    try:
        exchange = exchange_client.get_exchange()
        candles = exchange_client.fetch_closed_candles(
            exchange, symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT
        )
        if len(candles) < SWING_LENGTH * 3:
            return symbol, None
        signal = get_latest_signal(candles, swing_len=SWING_LENGTH, rr=TP_RR)
        return symbol, signal
    except Exception as e:
        logger.warning(f'掃描 {symbol} 失敗: {e}')
        return symbol, None


def check_open_signal(row: dict):
    """檢查單一筆『還沒結束』的訊號，最新K棒有沒有碰到止盈或止損。"""
    symbol = row['symbol']
    try:
        exchange = exchange_client.get_exchange()
        candles = exchange_client.fetch_closed_candles(exchange, symbol, timeframe=TIMEFRAME, limit=2)
        if not candles:
            return
        last_high, last_low = candles[-1][2], candles[-1][3]

        direction = row['direction']
        sl = row['sl_price']
        tp = row['tp_price']

        hit_sl = hit_tp = False
        if direction == 'long':
            if last_low <= sl:
                hit_sl = True
            elif tp is not None and last_high >= tp:
                hit_tp = True
        else:
            if last_high >= sl:
                hit_sl = True
            elif tp is not None and last_low <= tp:
                hit_tp = True

        if hit_sl or hit_tp:
            status = 'tp_hit' if hit_tp else 'sl_hit'
            exit_price = tp if hit_tp else sl
            database.close_signal(row['id'], status, int(time.time() * 1000))
            message = notifier.format_close_message(symbol, direction, status, row['entry_price'], exit_price)
            notifier.send_telegram_message(message)
            logger.info(f'{symbol} {direction} 已{"止盈" if hit_tp else "止損"}')
    except Exception as e:
        logger.warning(f'檢查未平倉訊號 {symbol} 失敗: {e}')


def check_open_signals():
    """檢查所有『還沒結束』的訊號，這個函式會在每次掃描時先執行。"""
    open_signals = database.get_open_signals()
    if not open_signals:
        return
    logger.info(f'檢查 {len(open_signals)} 筆未平倉訊號...')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(check_open_signal, open_signals))


def scan_market():
    """掃描整個市場，這個函式會被排程器定期呼叫。"""
    start_time = time.time()
    logger.info('開始掃描市場...')

    # 先檢查手上『還沒結束』的訊號有沒有止盈/止損
    check_open_signals()

    try:
        exchange = exchange_client.get_exchange()
        symbols = exchange_client.get_perpetual_symbols(exchange)
    except Exception as e:
        logger.error(f'取得幣種清單失敗: {e}')
        return

    logger.info(f'共 {len(symbols)} 個永續合約幣種，開始逐一掃描 (併發數: {MAX_WORKERS})')

    found_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_one_symbol, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, signal = future.result()
            if signal is None:
                continue

            already = database.signal_already_recorded(symbol, signal.direction, signal.candle_time)
            if already:
                continue

            detected_at = int(time.time() * 1000)
            database.record_signal(
                symbol, signal.direction, signal.entry_price, signal.sl_price, signal.tp_price,
                signal.candle_time, detected_at
            )
            message = notifier.format_signal_message(
                symbol, signal.direction, signal.entry_price, signal.sl_price, signal.tp_price, TIMEFRAME
            )
            notifier.send_telegram_message(message)
            found_count += 1
            logger.info(f'新訊號: {symbol} {signal.direction} @ {signal.entry_price}')

    elapsed = time.time() - start_time
    logger.info(f'掃描完成，耗時 {elapsed:.1f} 秒，共 {found_count} 個新訊號')


@app.route('/')
def index():
    import datetime
    signals = database.get_recent_signals(limit=100)
    for s in signals:
        dt = datetime.datetime.fromtimestamp(s['candle_time'] / 1000, tz=datetime.timezone.utc)
        dt_local = dt.astimezone()  # 轉成伺服器當地時區顯示
        s['time_str'] = dt_local.strftime('%Y-%m-%d %H:%M')
    return render_template('index.html', signals=signals, timeframe=TIMEFRAME)


@app.route('/chart/<path:symbol>')
def chart(symbol):
    tv_symbol = database.symbol_to_tradingview(symbol)
    return render_template('chart.html', symbol=symbol, tv_symbol=tv_symbol)


@app.route('/health')
def health():
    return {'status': 'ok'}


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_market, 'interval', minutes=SCAN_INTERVAL_MINUTES, id='scan_market_job')
    scheduler.start()
    logger.info(f'排程已啟動，每 {SCAN_INTERVAL_MINUTES} 分鐘掃描一次')
    return scheduler


database.init_db()
_scheduler = start_scheduler()

if __name__ == '__main__':
    # 啟動時先立刻跑一次，不用等第一個排程週期
    scan_market()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
