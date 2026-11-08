"""
從 BingX 抓你的成交紀錄（平倉紀錄 + 持倉中的單），寫進交易日誌。
金鑰只從環境變數讀：BINGX_API_KEY / BINGX_API_SECRET（請只開「讀取」權限）。
"""

import os
import time
import logging
import datetime
import threading

import ccxt

from .store import get_store, now_iso

logger = logging.getLogger(__name__)

DAY_MS = 24 * 3600 * 1000
WINDOW_MS = 7 * DAY_MS               # 每次只問 7 天，避免超過交易所的時間範圍限制
BACKFILL_DAYS = int(os.environ.get('JOURNAL_BACKFILL_DAYS', '90'))
OVERLAP_MS = 2 * DAY_MS               # 每次同步往回多抓 2 天，避免漏單

_sync_lock = threading.Lock()


def has_keys():
    return bool(os.environ.get('BINGX_API_KEY') and os.environ.get('BINGX_API_SECRET'))


def _exchange():
    return ccxt.bingx({
        'apiKey': os.environ.get('BINGX_API_KEY', ''),
        'secret': os.environ.get('BINGX_API_SECRET', ''),
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })


def _f(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(ms):
    ms = _f(ms)
    if not ms:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat()


def _norm_symbol(raw):
    # BNB-USDT -> BNBUSDT
    return (raw or '').replace('-', '').replace('/', '').replace(':USDT', '').upper()


def _side(rec):
    ps = str(rec.get('positionSide', '')).upper()
    if ps == 'LONG':
        return 'long'
    if ps == 'SHORT':
        return 'short'
    amt = _f(rec.get('positionAmt')) or 0
    return 'long' if amt >= 0 else 'short'


def _truthy(v, default=True):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 'yes')


def map_history(rec):
    qty = _f(rec.get('closePositionAmt')) or _f(rec.get('positionAmt'))
    net = _f(rec.get('netProfit'))
    gross = _f(rec.get('realisedProfit'))
    fee = _f(rec.get('positionCommission'))
    closed = _truthy(rec.get('closeAllPositions'), True)
    return {
        'external_id': str(rec.get('positionId')),
        'symbol': _norm_symbol(rec.get('symbol')),
        'side': _side(rec),
        'status': 'closed' if closed else 'open',
        'open_time': _iso(rec.get('openTime')),
        'close_time': _iso(rec.get('updateTime')) if closed else None,
        'entry': _f(rec.get('avgPrice')),
        'exit': _f(rec.get('avgClosePrice')),
        'qty': abs(qty) if qty is not None else None,
        'leverage': _f(rec.get('leverage')),
        'pnl': net if net is not None else gross,
        'gross_pnl': gross,
        'fee': abs(fee) if fee is not None else None,
        'funding': _f(rec.get('totalFunding')),
        'raw': rec,
    }


def map_open(rec):
    amt = _f(rec.get('positionAmt'))
    return {
        'external_id': str(rec.get('positionId')),
        'symbol': _norm_symbol(rec.get('symbol')),
        'side': _side(rec),
        'status': 'open',
        'open_time': _iso(rec.get('openTime') or rec.get('createTime') or rec.get('updateTime')),
        'close_time': None,
        'entry': _f(rec.get('avgPrice')),
        'exit': _f(rec.get('markPrice')),
        'qty': abs(amt) if amt is not None else None,
        'leverage': _f(rec.get('leverage')),
        'pnl': _f(rec.get('unrealizedProfit')),
        'gross_pnl': None,
        'fee': None,
        'funding': None,
        'raw': rec,
    }


def _data(resp):
    if not isinstance(resp, dict):
        return resp
    code = resp.get('code')
    if code not in (0, '0', None):
        raise RuntimeError(f"BingX 回傳錯誤 code={code} msg={resp.get('msg')}")
    return resp.get('data')


def _income_symbols(ex, start_ms, end_ms):
    """用資金流水（已實現盈虧、手續費）找出這段時間交易過哪些幣。"""
    syms = set()
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        data = _data(ex.swapV2PrivateGetUserIncome({'startTime': t, 'endTime': t2, 'limit': 1000})) or []
        for row in data:
            s = row.get('symbol')
            if s and str(row.get('incomeType', '')).upper() in ('REALIZED_PNL', 'TRADING_FEE', 'FUNDING_FEE', ''):
                syms.add(s)
        t = t2
        time.sleep(0.2)
    return syms


def _position_history(ex, symbol, start_ms, end_ms):
    out = []
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        page = 1
        while True:
            data = _data(ex.swapV1PrivateGetTradePositionHistory({
                'symbol': symbol, 'startTs': t, 'endTs': t2, 'pageIndex': page, 'pageSize': 100})) or {}
            rows = data.get('positionHistory', []) if isinstance(data, dict) else (data or [])
            out.extend(rows)
            if len(rows) < 100 or page >= 20:
                break
            page += 1
            time.sleep(0.2)
        t = t2
        time.sleep(0.2)
    return out


def _merge_into_stale_open(store, mapped, trades_cache):
    """持倉中的單平倉後，如果交易所給的 id 不一樣，就把它併回原本那筆，保留你補過的資料。"""
    ot = mapped.get('open_time')
    if not ot:
        return None
    try:
        t0 = datetime.datetime.fromisoformat(ot)
    except ValueError:
        return None
    for t in trades_cache:
        if t.get('source') != 'api' or t.get('status') != 'open' or t.get('deleted_at'):
            continue
        if t.get('symbol') != mapped['symbol'] or t.get('side') != mapped['side'] or not t.get('open_time'):
            continue
        try:
            t1 = datetime.datetime.fromisoformat(str(t['open_time']).replace('Z', '+00:00'))
        except ValueError:
            continue
        if abs((t1 - t0).total_seconds()) <= 180:
            return store.update_trade(t['id'], mapped)
    return None


def run_sync(full=False):
    """執行一次同步。回傳狀態 dict，也會存進 journal_kv('sync')。"""
    store = get_store()
    if not has_keys():
        st = {'ok': False, 'error': '還沒設定 BINGX_API_KEY / BINGX_API_SECRET', 'finished_at': now_iso()}
        store.put_kv('sync', dict(store.get_kv('sync', {}) or {}, **st))
        return st
    if not _sync_lock.acquire(blocking=False):
        return {'ok': True, 'running': True, 'message': '已經在同步中'}
    started = time.time()
    prev = store.get_kv('sync', {}) or {}
    st = dict(prev, running=True, started_at=now_iso(), error=None)
    store.put_kv('sync', st)
    try:
        ex = _exchange()
        now_ms = int(time.time() * 1000)
        last_ms = prev.get('last_end_ms')
        if full or not last_ms:
            start_ms = now_ms - BACKFILL_DAYS * DAY_MS
        else:
            start_ms = int(last_ms) - OVERLAP_MS

        open_rows = _data(ex.swapV2PrivateGetUserPositions({})) or []
        symbols = _income_symbols(ex, start_ms, now_ms)
        symbols |= {r.get('symbol') for r in open_rows if r.get('symbol')}
        # 曾經同步過、而且還在持倉中的幣也要查，才知道它平倉了
        trades_cache = store.list_trades()
        for t in trades_cache:
            if t.get('source') == 'api' and t.get('status') == 'open' and t.get('raw'):
                s = (t['raw'] or {}).get('symbol')
                if s:
                    symbols.add(s)

        added = updated = 0
        sample = None
        for sym in sorted(symbols):
            for rec in _position_history(ex, sym, start_ms, now_ms):
                m = map_history(rec)
                if not m['external_id'] or m['external_id'] == 'None':
                    continue
                sample = sample or rec
                existed = store.find_by_external(m['external_id'])
                if not existed and _merge_into_stale_open(store, m, trades_cache):
                    updated += 1
                    continue
                store.upsert_api_trade(m)
                if existed:
                    updated += 1
                else:
                    added += 1

        open_ids = set()
        for rec in open_rows:
            m = map_open(rec)
            if not m['external_id'] or m['external_id'] == 'None':
                continue
            open_ids.add(m['external_id'])
            existed = store.find_by_external(m['external_id'])
            if existed and existed.get('status') == 'closed':
                continue
            if existed and existed.get('open_time'):
                m.pop('open_time', None)   # 保留第一次看到的開倉時間
            store.upsert_api_trade(m)
            if existed:
                updated += 1
            else:
                added += 1

        st = dict(st, ok=True, running=False, finished_at=now_iso(), last_end_ms=now_ms,
                  added=added, updated=updated, symbols=sorted(symbols), open_count=len(open_ids),
                  seconds=round(time.time() - started, 1), error=None)
        if sample:
            st['sample'] = sample
        if full or not prev.get('backfilled'):
            st['backfilled'] = True
        store.put_kv('sync', st)
        logger.info(f'[日誌] 同步完成：新增 {added}、更新 {updated}，幣種 {len(symbols)}')
        return st
    except Exception as e:
        logger.exception('[日誌] 同步失敗')
        st = dict(st, ok=False, running=False, finished_at=now_iso(), error=f'{type(e).__name__}: {e}'[:500])
        store.put_kv('sync', st)
        return st
    finally:
        _sync_lock.release()


def sync_in_background(full=False):
    threading.Thread(target=run_sync, kwargs={'full': full}, daemon=True).start()


def maybe_sync_stale(minutes=5):
    """打開頁面時如果超過 5 分鐘沒同步（例如 Render 免費方案睡著了），就在背景補抓。"""
    if not has_keys():
        return
    st = get_store().get_kv('sync', {}) or {}
    last = st.get('last_end_ms')
    if st.get('running') and _sync_lock.locked():
        return
    if not last or time.time() * 1000 - float(last) > minutes * 60 * 1000:
        sync_in_background()
