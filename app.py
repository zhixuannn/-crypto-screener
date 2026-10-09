"""
XUAN 3+1 BingX 訊號掃描網站 (狀態持久化版)
"""

import os
import time
import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

import database
import exchange_client
import notifier
import cmc_client
import strategy
import lookup
import scoring
import xuan_scoring
import binance_data
import json
import hmac
import re

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
    cmc_symbols = cmc_client.get_top_symbols()
    if not cmc_symbols:
        logger.warning('CMC名單目前是空的(可能API Key未設定或第一次呼叫失敗)')
        return []
    bingx_map = build_bingx_symbol_map(exchange)
    scan_list = [
        bingx_map[sym] for sym in cmc_symbols
        if sym in bingx_map and sym.upper() not in STABLECOIN_SYMBOLS
    ]
    database.save_scan_symbols(scan_list, int(time.time() * 1000))
    return scan_list


# ==================== XUAN 3+1 ====================

def _scan_one_symbol_stateful_impl(symbol: str):
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
            logger.info(f'[XUAN] {symbol} 新幣種初始化完成，用了 {len(candles)} 根歷史K棒補記憶')
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
        logger.warning(f'[XUAN] 掃描 {symbol} 失敗: {e}')
        return symbol, []


# ==================== 每個幣種一把鎖 (排程掃描 和 TV 警報觸發 不會同時改同一個幣種的狀態) ====================

_symbol_locks = {}
_symbol_locks_guard = threading.Lock()
_signal_lock = threading.Lock()   # 讓『檢查有沒有重複 -> 記錄訊號』不會被兩個執行緒同時搶先


def _lock_for(key: str):
    with _symbol_locks_guard:
        if key not in _symbol_locks:
            _symbol_locks[key] = threading.Lock()
        return _symbol_locks[key]


def scan_one_symbol_stateful(symbol: str):
    with _lock_for(symbol):
        return _scan_one_symbol_stateful_impl(symbol)


# ==================== 未平倉檢查 ====================

def check_open_signal(row: dict):
    symbol = row['symbol']
    strategy_label = 'XUAN 3+1'
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
            message = notifier.format_close_message(symbol, direction, status, row['entry_price'], exit_price, strategy_label=strategy_label)
            notifier.send_telegram_message(message)
            logger.info(f'[{strategy_label}] {symbol} {direction} 已{"止盈" if hit_tp else "止損"}')
    except Exception as e:
        logger.warning(f'檢查未平倉訊號 {symbol} 失敗: {e}')


def check_open_signals():
    open_signals = [r for r in database.get_open_signals() if r.get('strategy', 'xuan') == 'xuan']
    if not open_signals:
        return
    logger.info(f'檢查 {len(open_signals)} 筆未平倉訊號...')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(check_open_signal, open_signals))


# ==================== 資料評分 (OI + CVD 背離) ====================

def score_and_filter(symbol: str, direction: str, timeframe: str, candle_time: int = 0):
    """
    回傳 (通過嗎, 分數dict或None)。XUAN 100 分制 (結構70 + 數據30)，門檻 SCORE_MIN (預設 0 = 全過)。
    - 資料抓不到 (幣安被擋、BingX K線失敗)：直接放行，不會因為抓不到資料而把訊號全擋掉。
    - 總分低於門檻：不通過 (不發 Telegram、不記錄)。
    """
    try:
        result = xuan_scoring.evaluate_xuan(symbol, direction, candle_time, timeframe)
        if result.get('incomplete'):
            logger.warning(f'[評分] {symbol} 部分資料抓不到，訊號放行 (目前總分 {result["total"]})')
            return True, result
    except Exception as e:
        logger.warning(f'[評分] {symbol} 計分發生錯誤，訊號放行且不計分: {e}')
        return True, None

    threshold = scoring.SCORE_MIN
    if result['total'] < threshold:
        logger.info(f'[評分] {symbol} {direction} {timeframe} 總分 {result["total"]}/{result["max"]} < 門檻 {threshold}，擋下')
        return False, result
    return True, result


def process_signals(symbol: str, signals: list, timeframe: str, source: str = 'site') -> dict:
    """
    把一個幣種新算出來的訊號：去重複 -> 打分數 -> 記錄 -> 發 Telegram。
    排程掃描和 TV 警報觸發都用這個函式，規則完全一樣。
    回傳 {'found','skipped_open','blocked'}。
    """
    strategy = 'xuan'
    counts = {'found': 0, 'skipped_open': 0, 'blocked': 0}
    for signal in signals:
        with _signal_lock:
            if database.has_open_signal(symbol, strategy=strategy, timeframe=timeframe):
                counts['skipped_open'] += 1
                continue
            if database.signal_already_recorded(symbol, signal.direction, signal.candle_time, strategy=strategy, timeframe=timeframe):
                continue
            passed, score = score_and_filter(symbol, signal.direction, timeframe, candle_time=signal.candle_time)
            if not passed:
                counts['blocked'] += 1
                continue
            database.record_signal(
                symbol, signal.direction, signal.entry_price, signal.sl_price, signal.tp_price,
                signal.candle_time, int(time.time() * 1000), strategy=strategy, timeframe=timeframe,
                score=score, source=source
            )
        message = notifier.format_signal_message(
            symbol, signal.direction, signal.entry_price, signal.sl_price, signal.tp_price, timeframe,
            strategy_label='XUAN 3+1', score=score, source=source
        )
        notifier.send_telegram_message(message)
        counts['found'] += 1
        score_text = (str(score['total']) + '/' + str(score['max'])) if score else '無'
        logger.info(f'[XUAN 3+1] 新訊號({source}): {symbol} {signal.direction} @ {signal.entry_price} 分數={score_text}')
    return counts


# ==================== 主掃描流程 ====================

def scan_market():
    start_time = time.time()
    logger.info('開始掃描市場...')

    check_open_signals()
    t_check = time.time() - start_time

    try:
        symbols = get_scan_symbols()
    except Exception as e:
        logger.error(f'取得幣種清單失敗: {e}')
        return

    if not symbols:
        logger.warning('這次掃描沒有可用的幣種清單，跳過本輪')
        return

    logger.info(f'共 {len(symbols)} 個幣種 (CMC前{cmc_client.TOP_N}大 ∩ BingX永續，已排除穩定幣)，開始逐一掃描 (併發數: {MAX_WORKERS})')

    found_count = 0
    skipped_already_open = 0
    blocked_by_score = 0

    t_scan0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_one_symbol_stateful, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, signals = future.result()
            c = process_signals(symbol, signals, TIMEFRAME)
            found_count += c['found']
            skipped_already_open += c['skipped_open']
            blocked_by_score += c['blocked']

    elapsed = time.time() - start_time
    logger.info(f'掃描完成，總耗時 {elapsed:.1f} 秒 (檢查未平倉 {t_check:.1f} 秒＋掃描幣種 {time.time() - t_scan0:.1f} 秒)，'
                f'共 {found_count} 個新訊號，{skipped_already_open} 個因已有未平倉訊號被跳過，'
                f'{blocked_by_score} 個因分數低於門檻被擋下 (門檻 {scoring.SCORE_MIN})')


# ==================== 資料整理 (給前端用) ====================

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


def _prepare_signals(signals, now_ms):
    for s in signals:
        dt = datetime.datetime.fromtimestamp(s['candle_time'] / 1000, tz=datetime.timezone.utc)
        dt_local = dt.astimezone()
        s['time_str'] = dt_local.strftime('%Y-%m-%d %H:%M')
        s['ago_str'] = time_ago_str(s['detected_at'], now_ms)
        s['base_symbol'] = s['symbol'].split('/')[0]
        raw_detail = s.get('score_detail')
        try:
            s['score_detail'] = json.loads(raw_detail) if raw_detail else []
        except Exception:
            s['score_detail'] = []
        s['score_max'] = s.get('score_max') or 40
    return signals


PRICE_TTL = 30
_price_cache = {}                 # symbol -> (抓取時間, 價格)
_price_lock = threading.Lock()


def _get_prices_cached(symbols):
    """即時價格：30 秒內抓過的直接用快取，只去抓缺的 (大幅減少對 BingX 的請求)。"""
    now = time.time()
    result, missing = {}, []
    with _price_lock:
        for s in symbols:
            hit = _price_cache.get(s)
            if hit and now - hit[0] < PRICE_TTL:
                result[s] = hit[1]
            else:
                missing.append(s)
    if missing:
        try:
            fresh = exchange_client.get_last_prices(exchange_client.get_exchange(), missing)
        except Exception as e:
            logger.warning(f'抓取即時價格失敗: {e}')
            fresh = {}
        with _price_lock:
            for s, p in fresh.items():
                _price_cache[s] = (now, p)
        result.update(fresh)
    return result


def _attach_live_pct(open_signals):
    if not open_signals:
        return
    last_prices = _get_prices_cached(list({s['symbol'] for s in open_signals}))
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


STATS_TTL = 30
_stats_cache = {}                 # (start, end) -> (時間, overall, per_symbol)
_stats_lock = threading.Lock()


def _get_stats_cached(start_ms, end_ms):
    """統計：同樣的時間範圍 30 秒內不重算。起訖時間取到『分鐘』，這樣『今天』這種範圍才會命中快取。"""
    key = (None if start_ms is None else start_ms // 60000, None if end_ms is None else end_ms // 60000)
    now = time.time()
    with _stats_lock:
        hit = _stats_cache.get(key)
        if hit and now - hit[0] < STATS_TTL:
            return hit[1], hit[2]
    overall, per_symbol = database.get_stats(start_ms, end_ms, strategy='xuan')
    with _stats_lock:
        _stats_cache[key] = (now, overall, per_symbol)
        if len(_stats_cache) > 50:
            for k in sorted(_stats_cache, key=lambda k: _stats_cache[k][0])[:25]:
                _stats_cache.pop(k, None)
    return overall, per_symbol


def build_dashboard_data(start_ms=None, end_ms=None) -> dict:
    t0 = time.time()
    now_ms = int(t0 * 1000)
    timing = {}

    xuan_signals = _prepare_signals(database.get_recent_signals(limit=200, strategy='xuan'), now_ms)
    xuan_open = [s for s in xuan_signals if s['status'] == 'open']
    xuan_closed = [s for s in xuan_signals if s['status'] != 'open']
    timing['signals'] = int((time.time() - t0) * 1000)

    t1 = time.time()
    _attach_live_pct(xuan_open)
    timing['prices'] = int((time.time() - t1) * 1000)

    scan_symbols_raw, symbols_updated_at = database.get_scan_symbols_cached()
    scan_symbols = [s.split('/')[0] for s in scan_symbols_raw]
    tv_symbol_map = {s.split('/')[0]: database.symbol_to_tradingview(s) for s in scan_symbols_raw}
    symbols_updated_str = None
    if symbols_updated_at:
        dt = datetime.datetime.fromtimestamp(symbols_updated_at / 1000, tz=datetime.timezone.utc)
        symbols_updated_str = dt.astimezone().strftime('%Y-%m-%d %H:%M')

    t2 = time.time()
    xuan_overall, xuan_per_symbol = _get_stats_cached(start_ms, end_ms)
    timing['stats'] = int((time.time() - t2) * 1000)
    timing['total'] = int((time.time() - t0) * 1000)
    logger.info(f'[載入速度] /api/data 共 {timing["total"]} ms (訊號 {timing["signals"]}／即時價 {timing["prices"]}／統計 {timing["stats"]})')

    return {
        'xuan_open_signals': xuan_open,
        'xuan_closed_signals': xuan_closed,
        'scan_symbols': scan_symbols,
        'tv_symbol_map': tv_symbol_map,
        'symbols_count': len(scan_symbols),
        'symbols_updated_str': symbols_updated_str,
        'xuan_overall_stats': xuan_overall,
        'xuan_per_symbol_stats': xuan_per_symbol,
        'timeframe': TIMEFRAME,
        'timing_ms': timing,
    }


# ==================== TV 警報 (Webhook) ====================

TV_WEBHOOK_SECRET = os.environ.get('TV_WEBHOOK_SECRET', '')
_tv_pool = ThreadPoolExecutor(max_workers=4)

TV_INTERVAL_MAP = {
    '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m',
    '60': '1h', '120': '2h', '240': '4h', '1D': '1d', 'D': '1d',
}


def normalize_tv_symbol(raw: str):
    """'BINGX:BTCUSDT.P' / 'BTCUSDT.P' / 'BTCUSDT' -> 'BTC/USDT:USDT'；看不懂回傳 None。"""
    if not raw:
        return None
    t = str(raw).upper().split(':')[-1]
    t = re.sub(r'\.P$', '', t)
    t = re.sub(r'(USDT|USDC|USD)$', '', t)
    t = re.sub(r'[^A-Z0-9]', '', t)
    return f'{t}/USDT:USDT' if t else None


def normalize_tv_timeframe(raw: str):
    r = str(raw or '').strip()
    if r in TV_INTERVAL_MAP:
        return TV_INTERVAL_MAP[r]
    if r.lower() in ('1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d'):
        return r.lower()
    return None


def handle_tv_alert(alert_id: int, symbol: str, timeframe: str, direction: str):
    """
    TV 警報來了：立刻對這個幣種跑一次掃描 (用網站自己的演算法算出進場/止損/止盈)，
    有訊號就記錄+打分+發 Telegram；已經有就只標記『TV ✓』。
    BingX 的K線偶爾會晚幾秒才出現，所以最多重試 3 次。
    """
    note = ''
    matched = False
    try:
        for attempt in range(3):
            _, signals = scan_one_symbol_stateful(symbol)
            process_signals(symbol, signals, timeframe, source='tv')
            n = database.mark_tv_confirmed(symbol, 'xuan', timeframe, direction,
                                            since_ms=int(time.time() * 1000) - 20 * 60 * 1000)
            if n:
                matched = True
                break
            time.sleep(20)
        if not matched:
            note = '網站沒算出同方向訊號 (可能被分數門檻擋下，或演算法判斷不同)'
            logger.warning(f'[TV警報] {symbol} {timeframe} {direction}: {note}')
    except Exception as e:
        note = f'處理失敗: {e}'
        logger.warning(f'[TV警報] 處理 {symbol} 失敗: {e}')
    database.update_tv_alert(alert_id, matched, note)


@app.route('/webhook/tv', methods=['POST'])
def webhook_tv():
    """
    TradingView 警報訊息範例 (JSON)：
    {"secret":"你的密碼","symbol":"{{ticker}}","tf":"{{interval}}","dir":"long"}
    """
    if not TV_WEBHOOK_SECRET:
        return jsonify({'ok': False, 'error': 'server secret not configured'}), 503
    data = request.get_json(force=True, silent=True) or {}
    given = str(data.get('secret', ''))
    if not hmac.compare_digest(given.encode(), TV_WEBHOOK_SECRET.encode()):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    symbol = normalize_tv_symbol(data.get('symbol'))
    timeframe = normalize_tv_timeframe(data.get('tf'))
    direction = str(data.get('dir', '')).lower()
    direction = {'buy': 'long', 'sell': 'short'}.get(direction, direction)

    if not symbol or not timeframe or direction not in ('long', 'short'):
        return jsonify({'ok': False, 'error': 'bad payload'}), 400
    if timeframe != TIMEFRAME:
        return jsonify({'ok': False, 'error': f'only {TIMEFRAME} is scanned'}), 400

    scan_list, _ = database.get_scan_symbols_cached()
    alert_id = database.record_tv_alert(symbol, 'xuan', timeframe, direction, int(time.time() * 1000))
    if symbol not in scan_list:
        database.update_tv_alert(alert_id, False, '這個幣不在網站的掃描名單 (CMC前150 ∩ BingX)，已忽略')
        return jsonify({'ok': True, 'ignored': 'symbol not in scan list'}), 200

    _tv_pool.submit(handle_tv_alert, alert_id, symbol, timeframe, direction)
    return jsonify({'ok': True}), 200


@app.route('/api/tv-alerts')
def api_tv_alerts():
    """最近收到的 TV 警報，以及網站有沒有對上 (用來檢查兩邊判斷是否一致)。"""
    return jsonify(database.get_recent_tv_alerts(50))


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


@app.route('/api/score-check')
def api_score_check():
    """檢查幣安資料連線是否正常 (部署到 Render 後打開這個網址就能確認有沒有被擋)。"""
    status = binance_data.ping()
    sample = None
    if status.get('ok'):
        sample = scoring.evaluate('BTC', 'long', '5m')
    xuan_sample = None
    try:
        xuan_sample = xuan_scoring.evaluate_xuan('BTC/USDT:USDT', 'long', int(time.time() * 1000), TIMEFRAME)
    except Exception as e:
        xuan_sample = {'error': str(e)}
    return jsonify({'binance': status, 'sample_btc_long_5m': sample, 'xuan_sample_btc_long': xuan_sample,
                    'score_min': scoring.SCORE_MIN})


@app.route('/api/lookup')
def api_lookup():
    """查幣：/api/lookup?symbol=SOL"""
    return jsonify(lookup.lookup(request.args.get('symbol', '')))


@app.route('/health')
def health():
    return {'status': 'ok'}


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_market, 'interval', minutes=SCAN_INTERVAL_MINUTES, id='scan_market_job')
    scheduler.start()
    logger.info(f'排程已啟動，每 {SCAN_INTERVAL_MINUTES} 分鐘掃描一次')
    return scheduler


def _startup_binance_check():
    status = binance_data.ping()
    if status.get('ok'):
        logger.info('[幣安] 連線測試成功，資料評分可正常使用')
    else:
        logger.warning(f'[幣安] 連線測試失敗: {status}。評分功能會自動略過 (訊號照常放行)。若是 451，代表這台伺服器的 IP 被幣安擋住')


database.init_db()
_scheduler = start_scheduler()
threading.Thread(target=_startup_binance_check, daemon=True).start()

if __name__ == '__main__':
    scan_market()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
