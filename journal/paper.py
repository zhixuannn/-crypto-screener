"""
紙上驗證：把掃描網站／TradingView 警報抓到的 XUAN 3+1 訊號當成「假設有下單」，
記成一筆 source='paper' 的交易，之後每 5 分鐘用 K 線檢查有沒有碰到止盈或停損。

- 每筆固定虧 1R = PAPER_RISK_U（預設 10U）
- 同一根 K 棒同時碰到止盈和停損：保守算停損
- 沒有時間停損：一直放到碰到其中一個為止
"""

import os
import time
import logging
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

from .store import get_store, now_iso

logger = logging.getLogger(__name__)

PAPER_RISK = float(os.environ.get('PAPER_RISK_U', '10'))
ORIGIN_NAME = {'site': '網站掃描', 'tv': 'TV 警報'}
TF_MS = {'1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000, '1h': 3_600_000, '4h': 14_400_000}

_settle_lock = threading.Lock()
_write_lock = threading.Lock()


def _iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat()


def _to_ms(v):
    try:
        return int(datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _journal_symbol(ccxt_symbol):
    return str(ccxt_symbol or '').split(':')[0].replace('/', '').replace('-', '').upper()


def _taker_pct():
    try:
        st = get_store().get_kv('settings', {}) or {}
        return float(st.get('takerFee', 0.05))
    except Exception:
        return 0.05


def _score_tag(score):
    try:
        total, mx = score.get('total'), score.get('max') or 100
        if total is None:
            return None
        pct = total / mx * 100
        return '分數 70+' if pct >= 70 else '分數 50–69' if pct >= 50 else '分數 50 以下'
    except Exception:
        return None


# ---------------------------------------------------------------- 記錄訊號
def _record(symbol, direction, entry, sl, tp, candle_time, timeframe, origin, score):
    store = get_store()
    if not entry or not sl or entry == sl:
        return
    jsym = _journal_symbol(symbol)
    ext = f'paper:{origin}:{jsym}:{timeframe}:{direction}:{int(candle_time)}'
    with _write_lock:
        if store.find_by_external(ext):
            return
        # 同一個來源、同一個幣、同一個週期已經有持倉中的紙上單，就不重複開（跟真的下單一樣一次只拿一筆）
        for t in store.list_trades(only_source='paper', status='open'):
            raw = t.get('raw') or {}
            if t.get('symbol') == jsym and raw.get('origin') == origin and raw.get('tf') == timeframe:
                return
        qty = PAPER_RISK / abs(entry - sl)
        side_word = '做多' if direction == 'long' else '做空'
        conds = [f'XUAN 3+1{side_word}', f'{timeframe} 訊號']
        tag = _score_tag(score) if score else None
        if tag:
            conds.append(tag)
        open_ms = int(candle_time) + TF_MS.get(timeframe, 300_000)   # 訊號那根收盤時進場
        store.insert_trade({
            'source': 'paper', 'external_id': ext, 'symbol': jsym, 'side': direction, 'status': 'open',
            'open_time': _iso(open_ms), 'entry': float(entry), 'sl': float(sl), 'tps': [float(tp)] if tp else [],
            'qty': qty, 'risk_amount': PAPER_RISK, 'setup': f'XUAN 3+1 · {ORIGIN_NAME.get(origin, origin)}',
            'order_type': 'market', 'conditions': conds,
            'raw': {'ccxt_symbol': symbol, 'tf': timeframe, 'origin': origin, 'candle_time': int(candle_time),
                    'score': (score or {}).get('total'), 'score_max': (score or {}).get('max')},
        })
    logger.info(f'[紙上] 新增 {jsym} {direction} {timeframe}（{ORIGIN_NAME.get(origin, origin)}）@ {entry}')


def record_signal(symbol, direction, entry, sl, tp, candle_time, timeframe, origin='site', score=None):
    """掃描流程呼叫這個；在背景寫入，不拖慢掃描。"""
    def run():
        try:
            _record(symbol, direction, entry, sl, tp, candle_time, timeframe, origin, score)
        except Exception:
            logger.exception('[紙上] 記錄訊號失敗')
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- 結算
def _check_trade(ex, t, taker):
    import exchange_client   # 掃描網站的共用模組（專案根目錄）
    raw = dict(t.get('raw') or {})
    sym, tf = raw.get('ccxt_symbol'), raw.get('tf') or '5m'
    entry, sl = float(t['entry']), float(t['sl'])
    tp = (t.get('tps') or [None])[0]
    if not sym:
        return None
    since = int(raw.get('checked_until') or raw.get('candle_time') or (_to_ms(t['open_time']) - TF_MS.get(tf, 300_000)))
    candles = exchange_client.fetch_new_closed_candles(ex, sym, tf, since_ms=since)
    long = t['side'] == 'long'
    tf_ms = TF_MS.get(tf, 300_000)
    for ts, _o, hi, lo, _c, _v in candles:
        hit_sl = lo <= sl if long else hi >= sl
        hit_tp = tp is not None and (hi >= tp if long else lo <= tp)
        if hit_sl or hit_tp:
            exit_px = sl if hit_sl else tp          # 同一根都碰到 → 保守算停損
            R = (exit_px - entry) / abs(entry - sl) * (1 if long else -1)
            qty = float(t.get('qty') or PAPER_RISK / abs(entry - sl))
            fee = (entry + exit_px) * qty * taker / 100
            gross = R * float(t.get('risk_amount') or PAPER_RISK)
            raw['exit_reason'] = 'sl' if hit_sl else 'tp'
            raw['checked_until'] = ts
            return {'status': 'closed', 'exit': exit_px, 'close_time': _iso(ts + tf_ms), 'gross_pnl': gross,
                    'fee': fee, 'pnl': gross - fee, 'raw': raw}
    if candles and candles[-1][0] - since > 6 * 3600_000:
        raw['checked_until'] = candles[-1][0]      # 記住檢查到哪，下次不用從頭抓
        return {'raw': raw}
    return None


def settle_open():
    """把持倉中的紙上單拿去比對 K 線，碰到止盈／停損就結算。"""
    if not _settle_lock.acquire(blocking=False):
        return {'skipped': True}
    try:
        import exchange_client
        store = get_store()
        opens = store.list_trades(only_source='paper', status='open')
        if not opens:
            return {'open': 0, 'closed': 0}
        taker = _taker_pct()
        closed = 0

        def one(t):
            ex = exchange_client.get_exchange()
            return t, _check_trade(ex, t, taker)

        with ThreadPoolExecutor(max_workers=4) as pool:
            for t, upd in pool.map(lambda x: _safe(one, x), opens):
                if upd:
                    store.update_trade(t['id'], upd)
                    if upd.get('status') == 'closed':
                        closed += 1
                        from . import notify
                        notify.paper_closed(t, upd)
        if closed:
            logger.info(f'[紙上] 結算 {closed} 筆（持倉中 {len(opens) - closed} 筆）')
        return {'open': len(opens) - closed, 'closed': closed}
    except Exception:
        logger.exception('[紙上] 結算失敗')
        return {'error': True}
    finally:
        _settle_lock.release()


def _safe(fn, t):
    try:
        return fn(t)
    except Exception as e:
        logger.warning(f"[紙上] 檢查 {t.get('symbol')} 失敗：{e}")
        return t, None
