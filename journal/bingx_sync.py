"""
從 BingX 抓你的成交紀錄，組成一筆一筆的交易，寫進交易日誌。
金鑰只從環境變數讀：BINGX_API_KEY / BINGX_API_SECRET（請只開「讀取」權限）。

做法：BingX 的「倉位歷史」介面對很多帳戶回傳是空的，所以改用「成交明細」(fillHistory)
自己把同一個方向的開倉、平倉成交串起來：倉位從 0 開始、回到 0 結束，就是一筆交易。
"""

import os
import json
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
OVERLAP_MS = 3 * DAY_MS               # 每次同步往回多抓 3 天，避免漏單、也抓得到較早的開倉

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
        return float(str(v).replace('X', '').replace('x', ''))
    except (TypeError, ValueError):
        return None


def _ms_to_iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat() if ms else None


def _parse_time(v):
    """BingX 的時間有時是毫秒數字，有時是 '2026-11-06T23:14:14.000+08:00'。統一轉成毫秒。"""
    if v is None or v == '':
        return None
    s = str(v)
    if s.isdigit():
        n = int(s)
        return n if n > 1e12 else n * 1000
    try:
        return int(datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return None


def _norm_symbol(raw):
    # BNB-USDT -> BNBUSDT
    return (raw or '').replace('-', '').replace('/', '').replace(':USDT', '').upper()


def _data(resp):
    if not isinstance(resp, dict):
        return resp
    code = resp.get('code')
    if code not in (0, '0', None):
        raise RuntimeError(f"BingX 回傳錯誤 code={code} msg={resp.get('msg')}")
    return resp.get('data')


# ---------------------------------------------------------------- 抓資料
def _income_symbols(ex, start_ms, end_ms):
    """用資金流水（已實現盈虧、手續費）找出這段時間交易過哪些幣。"""
    syms = set()
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        data = _data(ex.swapV2PrivateGetUserIncome({'startTime': t, 'endTime': t2, 'limit': 1000})) or []
        for row in data:
            if row.get('symbol'):
                syms.add(row['symbol'])
        t = t2
        time.sleep(0.15)
    return syms


def _fills_window(ex, symbol, t1, t2, depth=0):
    data = _data(ex.swapV2PrivateGetTradeFillHistory({'symbol': symbol, 'startTs': t1, 'endTs': t2})) or {}
    rows = data.get('fill_history_orders') or [] if isinstance(data, dict) else (data or [])
    total = _f(data.get('total')) if isinstance(data, dict) else None
    # 如果這段時間成交太多、一次沒給完，就把時間切一半再問
    if total and len(rows) < total and depth < 8 and t2 - t1 > 60_000:
        mid = (t1 + t2) // 2
        time.sleep(0.15)
        return _fills_window(ex, symbol, t1, mid, depth + 1) + _fills_window(ex, symbol, mid, t2, depth + 1)
    return rows


def _fills(ex, symbol, start_ms, end_ms):
    out, seen = [], set()
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        for r in _fills_window(ex, symbol, t, t2):
            key = r.get('tradeId') or (r.get('orderId'), r.get('filledTime'), r.get('qty'), r.get('price'))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        t = t2
        time.sleep(0.15)
    return out


def _leverage_map(ex, symbol, start_ms, end_ms):
    """訂單上才有槓桿，順便抓一下（抓不到就算了）。"""
    lev = {}
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        try:
            data = _data(ex.swapV2PrivateGetTradeAllOrders({'symbol': symbol, 'startTime': t, 'endTime': t2, 'limit': 1000})) or {}
            for o in (data.get('orders') or [] if isinstance(data, dict) else []):
                if o.get('orderId') and _f(o.get('leverage')):
                    lev[str(o['orderId'])] = _f(o.get('leverage'))
        except Exception:
            pass
        t = t2
        time.sleep(0.15)
    return lev


# ---------------------------------------------------------------- 把成交組成交易
def build_positions(symbol, fills, lev_map=None):
    """回傳 (已平倉的交易 list, 還沒平倉的倉位 list)。"""
    lev_map = lev_map or {}
    rows = []
    for r in fills:
        qty, price = _f(r.get('qty') or r.get('volume')), _f(r.get('price'))
        ts = _parse_time(r.get('filledTime') or r.get('filledTm') or r.get('time'))
        if not qty or not price or not ts:
            continue
        rows.append({'ts': ts, 'qty': abs(qty), 'price': price, 'side': str(r.get('side', '')).upper(),
                     'ps': str(r.get('positionSide', 'BOTH')).upper(), 'pnl': _f(r.get('realisedPNL')) or 0.0,
                     'fee': _f(r.get('commission')) or 0.0, 'oid': str(r.get('orderId') or ''), 'raw': r})
    rows.sort(key=lambda x: (x['ts'], x['oid']))
    books = {}
    closed, open_ = [], []

    def new_pos(direction, f):
        return {'dir': direction, 'open_ts': f['ts'], 'first_oid': f['oid'], 'qty': 0.0, 'opened': 0.0, 'open_val': 0.0,
                'closed_qty': 0.0, 'close_val': 0.0, 'pnl': 0.0, 'fee': 0.0, 'close_ts': None, 'fills': 0}

    for f in rows:
        if f['ps'] in ('LONG', 'SHORT'):
            direction = 'long' if f['ps'] == 'LONG' else 'short'
            opening = (direction == 'long' and f['side'] == 'BUY') or (direction == 'short' and f['side'] == 'SELL')
            key = direction
        else:  # 單向持倉：用目前倉位的方向判斷是開還是平
            key = 'both'
            cur = books.get(key)
            if cur and cur['qty'] > 1e-12:
                direction = cur['dir']
                opening = (direction == 'long') == (f['side'] == 'BUY')
            else:
                direction = 'long' if f['side'] == 'BUY' else 'short'
                opening = True
        pos = books.get(key)
        if opening:
            if not pos or pos['qty'] <= 1e-12:
                pos = books[key] = new_pos(direction, f)
            pos['qty'] += f['qty']
            pos['opened'] += f['qty']
            pos['open_val'] += f['qty'] * f['price']
            pos['fee'] += f['fee']
            pos['fills'] += 1
        else:
            if not pos or pos['qty'] <= 1e-12:
                continue   # 開倉在抓取範圍之前，這筆不完整，略過
            q = min(f['qty'], pos['qty'])
            pos['qty'] -= q
            pos['closed_qty'] += q
            pos['close_val'] += q * f['price']
            pos['pnl'] += f['pnl']
            pos['fee'] += f['fee']
            pos['close_ts'] = f['ts']
            pos['fills'] += 1
            if pos['qty'] <= max(1e-12, pos['opened'] * 1e-6):
                closed.append(pos)
                books[key] = None
    for pos in books.values():
        if pos and pos['qty'] > 1e-12:
            open_.append(pos)

    def to_trade(p, status):
        entry = p['open_val'] / p['opened'] if p['opened'] else None
        exit_ = p['close_val'] / p['closed_qty'] if p['closed_qty'] else None
        return {
            'external_id': f"fill:{symbol}:{p['dir']}:{p['first_oid']}:{p['open_ts']}",
            'symbol': _norm_symbol(symbol),
            'side': p['dir'],
            'status': status,
            'open_time': _ms_to_iso(p['open_ts']),
            'close_time': _ms_to_iso(p['close_ts']) if status == 'closed' else None,
            'entry': round(entry, 10) if entry else None,
            'exit': round(exit_, 10) if exit_ else None,
            'qty': round(p['opened'], 10),
            'leverage': lev_map.get(p['first_oid']),
            'pnl': round(p['pnl'] + p['fee'], 8) if status == 'closed' else None,   # 已實現盈虧 + 手續費（手續費是負數）
            'gross_pnl': round(p['pnl'], 8),
            'fee': round(-p['fee'], 8),
            'funding': None,
            'raw': {'symbol': symbol, 'fills': p['fills'], 'first_order_id': p['first_oid'], 'open_qty_left': round(p['qty'], 10)},
        }
    return [to_trade(p, 'closed') for p in closed], [to_trade(p, 'open') for p in open_]


# ---------------------------------------------------------------- 同步
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
        last_ms = prev.get('last_end_ms') if prev.get('engine') == 'fills' else None
        trades_cache = store.list_trades()
        if full or not last_ms:
            start_ms = now_ms - BACKFILL_DAYS * DAY_MS
        else:
            start_ms = int(last_ms) - OVERLAP_MS
        # 還在持倉中的單，要從它開倉那天開始抓，才組得回完整的一筆
        open_api = [t for t in trades_cache if t.get('source') == 'api' and t.get('status') == 'open' and not t.get('deleted_at')]
        for t in open_api:
            ms = _parse_time(t.get('open_time'))
            if ms:
                start_ms = min(start_ms, ms - 3600_000)

        live_positions = _data(ex.swapV2PrivateGetUserPositions({})) or []
        symbols = _income_symbols(ex, start_ms, now_ms)
        symbols |= {p.get('symbol') for p in live_positions if p.get('symbol')}
        symbols |= {(t.get('raw') or {}).get('symbol') for t in open_api if (t.get('raw') or {}).get('symbol')}
        symbols.discard(None)

        existing = {t.get('external_id'): t for t in trades_cache if t.get('external_id')}
        added = updated = 0
        seen_open = set()
        sample = None
        fills_total = 0
        for sym in sorted(symbols):
            fills = _fills(ex, sym, start_ms, now_ms)
            fills_total += len(fills)
            if not fills:
                continue
            sample = sample or fills[-1]
            lev = _leverage_map(ex, sym, start_ms, now_ms)
            closed, opened = build_positions(sym, fills, lev)
            live = {(_norm_symbol(p.get('symbol')), 'long' if str(p.get('positionSide')).upper() == 'LONG' or (_f(p.get('positionAmt')) or 0) > 0 else 'short'): p for p in live_positions}
            for m in opened:
                lp = live.get((m['symbol'], m['side']))
                if lp:   # 交易所說還在持倉：補上未實現盈虧
                    m['pnl'] = _f(lp.get('unrealizedProfit'))
                    m['exit'] = _f(lp.get('markPrice'))
                    m['leverage'] = m['leverage'] or _f(lp.get('leverage'))
                seen_open.add(m['external_id'])
            for m in closed + opened:
                ex_t = existing.get(m['external_id'])
                if ex_t and ex_t.get('status') == 'closed' and m['status'] == 'open':
                    continue
                store.upsert_api_trade(m)
                if ex_t:
                    updated += 1
                else:
                    added += 1

        st = dict(st, ok=True, running=False, finished_at=now_iso(), last_end_ms=now_ms, engine='fills',
                  added=added, updated=updated, symbols=sorted(symbols), open_count=len(seen_open), fills=fills_total,
                  seconds=round(time.time() - started, 1), error=None)
        if sample:
            st['sample'] = sample
        if full or not prev.get('backfilled'):
            st['backfilled'] = True
        store.put_kv('sync', st)
        logger.info(f'[日誌] 同步完成：成交 {fills_total} 筆 → 新增 {added}、更新 {updated}，幣種 {len(symbols)}')
        return st
    except Exception as e:
        logger.exception('[日誌] 同步失敗')
        st = dict(st, ok=False, running=False, finished_at=now_iso(), error=f'{type(e).__name__}: {e}'[:500])
        store.put_kv('sync', st)
        return st
    finally:
        _sync_lock.release()


def debug_probe(symbol='BTC-USDT', days=7):
    """除錯用：直接回傳交易所的原始回應（不含金鑰）。"""
    ex = _exchange()
    now = int(time.time() * 1000)
    start = now - days * DAY_MS
    out = {}
    calls = {
        'fillHistory': lambda: ex.swapV2PrivateGetTradeFillHistory({'symbol': symbol, 'startTs': start, 'endTs': now}),
        'positionHistory': lambda: ex.swapV1PrivateGetTradePositionHistory({'symbol': symbol, 'startTs': start, 'endTs': now}),
        'income': lambda: ex.swapV2PrivateGetUserIncome({'symbol': symbol, 'startTime': start, 'endTime': now, 'limit': 20}),
        'positions': lambda: ex.swapV2PrivateGetUserPositions({}),
    }
    for name, fn in calls.items():
        try:
            txt = json.dumps(fn(), ensure_ascii=False, default=str)
            out[name] = json.loads(txt) if len(txt) <= 8000 else {'_truncated': txt[:8000]}
        except Exception as e:
            out[name] = {'_error': f'{type(e).__name__}: {e}'[:600]}
    return out


def sync_in_background(full=False):
    threading.Thread(target=run_sync, kwargs={'full': full}, daemon=True).start()
