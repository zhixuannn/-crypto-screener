"""
查幣功能：輸入任何一個 BingX USDT 永續合約的代號 (例如 SOL)，
回傳這隻幣『現在』的狀況：價格、各週期偏見、15m/5m 結構、時段、偏見完成了沒、4H 流動性獵取，
以及『如果現在做多／做空』會拿幾分 (只是試算，不會發訊號、不會記錄)。

一次查詢大約 6 次資料請求 (5 組 BingX K線 + 行情)，同時進行；
同一隻幣 60 秒內重複查會直接用快取，不再重抓。
"""

import re
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import exchange_client
import xuan_scoring
import smc_structure
import bias
import database
import snapshot
import okx_data

logger = logging.getLogger(__name__)

CACHE_TTL = 60
_cache = {}          # base -> (時間, 結果)
_cache_lock = threading.Lock()

_DIR_WORD = {'long': '偏多', 'short': '偏空', None: '不明'}


def sanitize(raw: str) -> str:
    """'  sol/usdt ' -> 'SOL'。只留英數。"""
    t = str(raw or '').upper().strip()
    t = re.sub(r'[^A-Z0-9/:.]', '', t)
    t = t.split(':')[0].split('/')[0]
    t = re.sub(r'\.P$', '', t)
    if t.endswith('USDT') and len(t) > 4:
        t = t[:-4]
    return re.sub(r'[^A-Z0-9]', '', t)[:20]


def find_symbol(base: str):
    """回傳 (完整交易對或None, 相似的代號清單)。"""
    ex = exchange_client.get_exchange()
    bases = {}
    for s in exchange_client.get_perpetual_symbols(ex):
        bases[s.split('/')[0]] = s
    if base in bases:
        return bases[base], []
    similar = sorted(b for b in bases if b.startswith(base) or (len(base) >= 3 and base in b))[:8]
    return None, similar


def _struct_view(candles):
    st = smc_structure.structure_state(candles) if candles else None
    if st is None:
        return None
    return {'break_dir': st['break_dir'], 'arrangement': st['arrangement']}


def lookup(raw_symbol: str) -> dict:
    t0 = time.time()
    base = sanitize(raw_symbol)
    if not base:
        return {'ok': False, 'error': '請輸入幣種代號，例如 SOL'}

    with _cache_lock:
        hit = _cache.get(base)
        if hit and time.time() - hit[0] < CACHE_TTL:
            out = dict(hit[1])
            out['cached'] = True
            return out

    try:
        symbol, similar = find_symbol(base)
    except Exception as e:
        logger.warning(f'[查幣] 取得市場清單失敗: {e}')
        return {'ok': False, 'error': '暫時連不上 BingX，請稍後再試'}
    if not symbol:
        return {'ok': False, 'error': f'BingX 找不到 {base} 的 USDT 永續合約', 'similar': similar}

    def job_ticker():
        try:
            return exchange_client.get_ticker_info(exchange_client.get_exchange(), symbol)
        except Exception as e:
            logger.warning(f'[查幣] {symbol} 行情失敗: {e}')
            return {'price': None, 'change_24h': None}

    def job_lights():   # 偏見紅綠燈（15m/30m/1h/4h/1d），跟訊號卡片同一套
        try:
            return snapshot.compute_lights(symbol, int(time.time() * 1000))
        except Exception as e:
            logger.warning(f'[查幣] {symbol} 紅綠燈失敗: {e}')
            return None

    def job_6h():   # 6H 偏見用（評分本身沒有用到 6H，這裡另外抓）
        try:
            return exchange_client.fetch_closed_candles(exchange_client.get_exchange(), symbol, timeframe='6h', limit=6)
        except Exception as e:
            logger.warning(f'[查幣] {symbol} 6H K線失敗: {e}')
            return None

    def job_market():   # BingX 資金費率、持倉量
        try:
            return snapshot.market_data(symbol)
        except Exception as e:
            logger.warning(f'[查幣] {symbol} 合約數據失敗: {e}')
            return {}

    def job_okx():      # OKX 多空人數比、CVD（15 分鐘）
        try:
            return okx_data.flow(base)
        except Exception as e:
            logger.warning(f'[查幣] {base} OKX 失敗: {e}')
            return {'ok': False, 'error': 'OKX 數據暫時抓不到'}

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_market = pool.submit(job_market)
        f_okx = pool.submit(job_okx)
        f_ticker = pool.submit(job_ticker)
        f_gather = pool.submit(xuan_scoring.gather, symbol, '5m')
        f_lights = pool.submit(job_lights)
        f_6h = pool.submit(job_6h)
        ticker = f_ticker.result()
        inputs = f_gather.result()
        lights = f_lights.result()
        c6h = f_6h.result()
        market = f_market.result() or {}
        okx = f_okx.result()

    now_ms = int(time.time() * 1000)
    candles = inputs['candles']
    hour = bias.tw_hour(now_ms)
    sess_code, sess_label = bias.day_session(hour)
    h4 = bias.hour_in_4h(hour)

    biases = {}
    for tf in ('1d', '6h', '4h', '1h'):
        c = c6h if tf == '6h' else candles.get(tf)
        biases[tf] = bias.bias_direction(c) if c and len(c) >= 2 else None

    # 斐波那契 0.5：昨天日 K（台灣早上 8 點開盤那根，已收盤）的 (高＋低) ÷ 2，跟 3+1 指標的 FIB 0.5 一樣
    fib = None
    c1d = candles.get('1d')
    if c1d:
        day_open = now_ms // 86_400_000 * 86_400_000
        prev = [c for c in c1d if c[0] < day_open]
        if prev:
            hi, lo = prev[-1][2], prev[-1][3]
            level = (hi + lo) / 2
            price = ticker.get('price')
            fib = {'level': level, 'high': hi, 'low': lo,
                   'side': None if price is None else ('above' if price > level else 'below' if price < level else 'at'),
                   'dist_pct': None if price is None or not level else (price - level) / level * 100}

    score_long = xuan_scoring.score(inputs, 'long', now_ms)
    score_short = xuan_scoring.score(inputs, 'short', now_ms)
    note_of = lambda sc, key: next((i['n'] for i in sc['detail'] if i['k'] == key), '無資料')

    result = {
        'ok': True,
        'symbol': symbol,
        'base': base,
        'tv_symbol': database.symbol_to_tradingview(symbol),
        'price': ticker['price'],
        'change_24h': ticker['change_24h'],
        'bias': {tf: {'dir': d, 'text': _DIR_WORD[d]} for tf, d in biases.items()},
        'structure': {'15m': _struct_view(candles.get('15m')), '5m': _struct_view(candles.get('5m'))},
        'session': {'code': sess_code, 'label': sess_label, 'hour_in_4h': h4,
                    'good_4h': h4 == 3, 'tw_hour': hour},
        'pending': {'long': note_of(score_long, 'bias_pending'), 'short': note_of(score_short, 'bias_pending')},
        'sweep': {'long': note_of(score_long, 'liq_4h'), 'short': note_of(score_short, 'liq_4h')},
        'score_long': score_long,
        'score_short': score_short,
        'open_signal': database.get_open_signal_for_symbol(symbol),
        'lights': lights,
        'fib': fib,
        'market': {'funding_rate': market.get('funding_rate'), 'open_interest': market.get('open_interest')},
        'okx': okx,
        'incomplete': inputs['incomplete'],
        'cached': False,
        'ts': now_ms,
    }
    result['took_ms'] = int((time.time() - t0) * 1000)
    logger.info(f'[查幣] {symbol} 完成，耗時 {result["took_ms"]} ms')

    with _cache_lock:
        _cache[base] = (time.time(), result)
        if len(_cache) > 200:
            oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:50]
            for k, _ in oldest:
                _cache.pop(k, None)
    return result
