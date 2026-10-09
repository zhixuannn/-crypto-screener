"""
查幣功能：輸入任何一個 BingX USDT 永續合約的代號 (例如 SOL)，
回傳這隻幣『現在』的狀況：價格、各週期偏見、15m/5m 結構、時段、OI/CVD，
以及『如果現在做多／做空』會拿幾分 (只是試算，不會發訊號、不會記錄)。

一次查詢大約 7 次資料請求 (5 組 BingX K線 + 幣安 OI/K線 + 行情)，同時進行；
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
import scoring
import bias
import database

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

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ticker = pool.submit(job_ticker)
        f_gather = pool.submit(xuan_scoring.gather, symbol, '5m')
        ticker = f_ticker.result()
        inputs = f_gather.result()

    now_ms = int(time.time() * 1000)
    candles = inputs['candles']
    hour = bias.tw_hour(now_ms)
    sess_code, sess_label = bias.day_session(hour)
    h4 = bias.hour_in_4h(hour)

    biases = {}
    for tf in ('1d', '4h', '1h'):
        c = candles.get(tf)
        biases[tf] = bias.bias_direction(c) if c and len(c) >= 2 else None

    oi_note = cvd_note = '無資料'
    if inputs.get('binance_ok') and inputs.get('binance'):
        raw = scoring.score_from_inputs('long', inputs['binance'])
        oi_note, _, cvd_note = raw['note'].partition(' | ')

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
                    'good_4h': h4 in (2, 3), 'tw_hour': hour},
        'oi': oi_note,
        'cvd': cvd_note,
        'score_long': xuan_scoring.score(inputs, 'long', now_ms),
        'score_short': xuan_scoring.score(inputs, 'short', now_ms),
        'open_signal': database.get_open_signal_for_symbol(symbol),
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
