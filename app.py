"""
XUAN 3+1 BingX 訊號掃描網站 (狀態持久化版)
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

TIMEFRAME = os.environ.get('SCAN_TIMEFRAME', '5m')
SCAN_INTERVAL_MINUTES = int(os.environ.get('SCAN_INTERVAL_MINUTES', '5'))
SWING_LENGTH = int(os.environ.get('SWING_LENGTH', '5'))
BOOTSTRAP_CANDLE_LIMIT = int(os.environ.get('BOOTSTRAP_CANDLE_LIMIT', '1000'))
MAX_WORKERS = int(os.environ.get('SCAN_MAX_WORKERS', '5'))
TP_RR = float(os.environ.get('TP_RR', '1.0'))

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
    perp_symbols = exchange_client.get_perpetual_symbols(exchange)
    mapping = {}
    for s in perp_symbols:
        base = s.split('/')[0]
        mapping[base] = s
    return mapping


def get_scan_symbols() -> list:
    exchange = exchange_client.get_exchange()
    cmc_symbols = cmc_client.get_top100_symbols()
    if not cmc_symbols:
        logger.warning('CMC前100大名單目前是空的(可能API Key未設定或第一次呼叫失敗)')
        return []
    bingx_map = build_bingx_symbol_map(exchange)
    scan_list = [
        bingx_map[sym] for sym in cmc_symbols
        if sym in bingx_map and sym.upper() not in STABLECOIN_SYMBOLS
    ]
    database.save_scan_symbols(scan_list, int(time.time() * 1000))
    return scan_list


def scan_one_symbol_stateful(symbol: str):
    try:
        exchange = exchange_client.get_exchange()
        state_row = database.get_symbol_state(symbol)
        is_new = state_row is None

        if is_new:
            candles = exchange_client.fetch_closed_candles(
                exchange, symbol, timeframe=TIMEFRAME, limit=BOOTSTRAP_CANDLE_LIMIT
            )
            if len(candles) < SWING_LENGTH * 3:
                return symbol, []
            state = strategy.new_state(swing_len=SWING_LENGTH)
            state, _bootstrap_signals = strategy.advance_state(state, candles, rr=TP_RR)
            last_candle_time = candles[-1][0]
            logger.info(f'{symbol} 新幣種初始化完成，用了 {len(candles)} 根歷史K棒補記憶')
            result_signals = []
        else:
            state_json, last_candle_time = state_row
            state = strategy.state_from_json(state_json)
            new_candles = exchange_client.fetch_new_closed_candles(
                exchange, symbol, timeframe=TIMEFRAME, since_ms=last_candle_time
            )
            if not new_candles:
                return symbol, []
            state, result_signals = strategy.advance_state(state, new_candles, rr=TP_RR)
            last_candle_time = new_candles[-1][0]

        database.save_symbol_state(
            symbol, strategy.state_to_json(state), last_candle_time, int(time.time() * 1000)
        )
        return symbol, result_signals
    except Exception as e:
        logger.warning(f'掃描 {symbol} 失敗: {e}')
        return symbol, []


def check_open_signal(row: dict):
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
    open_signals = database.get_open_signals()
    if not open_signals:
        return
    logger.info(f'檢查 {len(open_signals)} 筆未平倉訊號...')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(check_open_signal, open_signals))


def scan_market():
    start_time = time.time()
    logger.info('開始掃描市場...')

    check_open_signals()

    try:
        symbols = get_scan_symbols()
    except Exception as e:
        logger.error(f'取得幣種清單失敗: {e}')
        return

    if not symbols:
        logger.warning('這次掃描沒有可用的幣種清單，跳過本輪')
        return

    logger.info(f'共 {len(symbols)} 個幣種 (CMC前100大 ∩ BingX永續，已排除穩定幣)，開始逐一掃描 (併發數: {MAX_WORKERS})')

    found_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_one_symbol_stateful, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, signals = future.result()
            for signal in signals:
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


def resolve_time_range(args):
    range_param = args.get('range', 'today')
    now = datetime.datetime.now(tz=TW_TZ)
    now_ms = int(now.timestamp() * 1000)

    if range_param == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(start.timestamp() * 1000), now_ms
    if range_param == '7d':
        return now_ms - 7 * 24 * 3600 * 1000, now_ms
    if range_param == '30d':
        return now_ms - 30 * 24 * 3600 * 1000, now_ms
    if range_param == 'custom':
        start_str = args.get('start')
        end_str = args.get('end')
        start_ms = end_ms = None
        if start_str:
            start_dt = datetime.datetime.strptime(start_str, '%Y-%m-%d').replace(tzinfo=TW_TZ)
            start_ms = int(start_dt.timestamp() * 1000)
        if end_str:
            end_dt = datetime.datetime.strptime(end_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999000, tzinfo=TW_TZ
            )
            end_ms = int(end_dt.timestamp() * 1000)
        return start_ms, end_ms
    return None, None


def build_dashboard_data(start_ms=None, end_ms=None) -> dict:
    signals = database.get_recent_signals(limit=200)
    now_ms = int(time.time() * 1000)
    for s in signals:
        dt = datetime.datetime.fromtimestamp(s['candle_time'] / 1000, tz=datetime.timezone.utc)
        dt_local = dt.astimezone()
        s['time_str'] = dt_local.strftime('%Y-%m-%d %H:%M')
        s['ago_str'] = time_ago_str(s['detected_at'], now_ms)
        s['base_symbol'] = s['symbol'].split('/')[0]

    open_signals = [s for s in signals if s['status'] == 'open']
    closed_signals = [s for s in signals if s['status'] != 'open']

    if open_signals:
        try:
            exchange = exchange_client.get_exchange()
            open_symbols = list({s['symbol'] for s in open_signals})
            last_prices = exchange_client.get_last_prices(exchange, open_symbols)
        except Exception as e:
            logger.warning(f'抓取即時價格失敗: {e}')
            last_prices = {}
        for s in open_signals:
            last_price = last_prices.get(s['symbol'])
            if last_price is not None:
                entry = s['entry_price']
                if s['direction'] == 'long':
                    s['live_pct'] = (last_price - entry) / entry * 100
                else:
                    s['live_pct'] = (entry - last_price) / entry * 100
            else:
                s['live_pct'] = None

    scan_symbols_raw, symbols_updated_at = database.get_scan_symbols_cached()
    scan_symbols = [s.split('/')[0] for s in scan_symbols_raw]
    tv_symbol_map = {s.split('/')[0]: database.symbol_to_tradingview(s) for s in scan_symbols_raw}
    symbols_updated_str = None
    if symbols_updated_at:
        dt = datetime.datetime.fromtimestamp(symbols_updated_at / 1000, tz=datetime.timezone.utc)
        symbols_updated_str = dt.astimezone().strftime('%Y-%m-%d %H:%M')

    overall_stats, per_symbol_stats = database.get_stats(start_ms, end_ms)

    return {
        'open_signals': open_signals,
        'closed_signals': closed_signals,
        'scan_symbols': scan_symbols,
        'tv_symbol_map': tv_symbol_map,
        'symbols_count': len(scan_symbols),
        'symbols_updated_str': symbols_updated_str,
        'overall_stats': overall_stats,
        'per_symbol_stats': per_symbol_stats,
        'timeframe': TIMEFRAME,
    }


@app.route('/')
def index():
    return render_template('index.html', timeframe=TIMEFRAME)


@app.route('/api/data')
def api_data():
    start_ms, end_ms = resolve_time_range(request.args)
    return jsonify(build_dashboard_data(start_ms, end_ms))


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
    scan_market()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
