"""
從 BingX 抓你的平倉紀錄和持倉中的單，寫進交易日誌。
金鑰只從環境變數讀：BINGX_API_KEY / BINGX_API_SECRET（請只開「讀取」權限）。

注意：BingX 的倉位歷史 (positionHistory) 用 7 天的區間去問會回傳空的，
用 30 天的區間才會給資料，所以這裡一次問 30 天。
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
WINDOW_MS = 30 * DAY_MS
BACKFILL_DAYS = int(os.environ.get('JOURNAL_BACKFILL_DAYS', '90'))
OVERLAP_MS = 3 * DAY_MS
USER_KEYS = ('sl', 'risk_amount', 'setup', 'note', 'reason', 'rule_note')
USER_LISTS = ('conditions', 'emotions', 'mistakes', 'shots', 'tv_links', 'tps')

_guard = threading.Lock()
_running_since = [0.0]          # 同步開始的時間；超過 10 分鐘還沒結束就當它卡住了，允許重新開始
STALE_SECONDS = 600


class _SyncLock:
    """給 routes 用的相容介面：locked() 代表「正在同步」。"""
    def locked(self):
        return bool(_running_since[0]) and time.time() - _running_since[0] < STALE_SECONDS


_sync_lock = _SyncLock()


def _try_start():
    with _guard:
        if _sync_lock.locked():
            return False
        _running_since[0] = time.time()
        return True


def _finish():
    with _guard:
        _running_since[0] = 0.0


def has_keys():
    return bool(os.environ.get('BINGX_API_KEY') and os.environ.get('BINGX_API_SECRET'))


def _exchange():
    return ccxt.bingx({
        'apiKey': os.environ.get('BINGX_API_KEY', ''),
        'secret': os.environ.get('BINGX_API_SECRET', ''),
        'enableRateLimit': True,
        'timeout': 15000,
        'options': {'defaultType': 'swap'},
    })


def _f(v):
    try:
        if v is None or v == '':
            return None
        return float(str(v).replace('X', '').replace('x', ''))
    except (TypeError, ValueError):
        return None


def _iso(ms):
    ms = _f(ms)
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat() if ms else None


def _to_ms(v):
    if not v:
        return None
    try:
        return int(datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return None


def _norm_symbol(raw):
    return (raw or '').replace('-', '').replace('/', '').replace(':USDT', '').upper()


def _side(rec):
    ps = str(rec.get('positionSide', '')).upper()
    if ps in ('LONG', 'SHORT'):
        return ps.lower()
    return 'long' if (_f(rec.get('positionAmt')) or 0) >= 0 else 'short'


def _data(resp):
    if not isinstance(resp, dict):
        return resp
    code = resp.get('code')
    if code not in (0, '0', None):
        raise RuntimeError(f"BingX 回傳錯誤 code={code} msg={resp.get('msg')}")
    return resp.get('data')


def _has_user_data(t):
    return any(t.get(k) not in (None, '') for k in USER_KEYS) or any(t.get(k) for k in USER_LISTS)


# ---------------------------------------------------------------- 轉換
def map_history(rec):
    qty = _f(rec.get('closePositionAmt')) or _f(rec.get('positionAmt'))
    net, gross, fee = _f(rec.get('netProfit')), _f(rec.get('realisedProfit')), _f(rec.get('positionCommission'))
    closed = str(rec.get('closeAllPositions', True)).lower() in ('true', '1')
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
        'pnl': net if net is not None else gross,      # BingX 淨盈虧（已扣手續費與資金費）
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
        'gross_pnl': None, 'fee': None, 'funding': None,
        'raw': rec,
    }


# ---------------------------------------------------------------- 抓資料
def _income_symbols(ex, start_ms, end_ms):
    """用資金流水找出這段時間交易過哪些幣（資金流水一次問 7 天）。"""
    syms, t = set(), start_ms
    while t < end_ms:
        t2 = min(t + 7 * DAY_MS, end_ms)
        for row in _data(ex.swapV2PrivateGetUserIncome({'startTime': t, 'endTime': t2, 'limit': 1000})) or []:
            if row.get('symbol'):
                syms.add(row['symbol'])
        t = t2
        time.sleep(0.15)
    return syms


def _position_history(ex, symbol, start_ms, end_ms):
    out, seen = [], set()
    t = start_ms
    while t < end_ms:
        t2 = min(t + WINDOW_MS, end_ms)
        if t2 - t < WINDOW_MS:          # 區間太短會拿到空的，往前補滿 30 天
            t = max(0, t2 - WINDOW_MS)
        page = 0                        # 第一次不帶分頁參數（帶了反而會拿到空的）
        while True:
            params = {'symbol': symbol, 'startTs': t, 'endTs': t2}
            if page:
                params.update(pageIndex=page, pageSize=100)
            data = _data(ex.swapV1PrivateGetTradePositionHistory(params)) or {}
            rows = data.get('positionHistory', []) if isinstance(data, dict) else (data or [])
            new = 0
            for r in rows:
                if r.get('positionId') not in seen:
                    seen.add(r.get('positionId'))
                    out.append(r)
                    new += 1
            if len(rows) < 100 or not new or page >= 20:
                break
            page = 2 if not page else page + 1
            time.sleep(0.15)
        t = t2
        time.sleep(0.15)
    return out


def _orders(ex, symbol, start_ms, end_ms):
    """抓這段時間的所有委託（含已取消的停損單），一次問 7 天。"""
    out, seen, t = [], set(), start_ms
    while t < end_ms:
        t2 = min(t + 7 * DAY_MS, end_ms)
        data = _data(ex.swapV2PrivateGetTradeAllOrders({'symbol': symbol, 'startTime': t, 'endTime': t2, 'limit': 1000})) or {}
        rows = data.get('orders', []) if isinstance(data, dict) else (data or [])
        for r in rows:
            oid = r.get('orderId')
            if oid not in seen:
                seen.add(oid)
                out.append(r)
        t = t2
        time.sleep(0.15)
    return out


def _attached_stop(od):
    """下單時一起帶的停損（stopLoss 欄位，可能是物件或 JSON 字串）。"""
    v = od.get('stopLoss')
    if isinstance(v, str) and v.strip().startswith('{'):
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    if isinstance(v, dict):
        return _f(v.get('stopPrice')) or _f(v.get('price'))
    return None


def _infer_sl(m, orders, now_ms):
    """從委託紀錄找這筆倉位「最早設的保護性停損價」。找不到回傳 None。"""
    side, entry = m.get('side'), m.get('entry')
    o_ms, c_ms = _to_ms(m.get('open_time')), _to_ms(m.get('close_time')) or now_ms
    if not entry or not o_ms:
        return None
    open_side, close_side = ('BUY', 'SELL') if side == 'long' else ('SELL', 'BUY')
    best = None
    for od in orders:
        ps = str(od.get('positionSide', '')).upper()
        if ps in ('LONG', 'SHORT') and ps.lower() != side:
            continue
        ts = _f(od.get('time')) or _f(od.get('updateTime'))
        if not ts:
            continue
        typ = str(od.get('type', '')).upper()
        oside = str(od.get('side', '')).upper()
        price = None
        if typ in ('STOP_MARKET', 'STOP') and oside == close_side and o_ms - 60_000 <= ts <= c_ms:
            price = _f(od.get('stopPrice'))
        elif oside == open_side and o_ms - 3 * DAY_MS <= ts <= o_ms + 60_000:
            price = _attached_stop(od)
        if not price:
            continue
        protective = price < entry if side == 'long' else price > entry
        if not protective or abs(price - entry) / entry > 0.5:
            continue
        if best is None or ts < best[0]:
            best = (ts, price)
    return best[1] if best else None


# ---------------------------------------------------------------- 同步
def run_sync(full=False):
    store = get_store()
    if not has_keys():
        st = {'ok': False, 'error': '還沒設定 BINGX_API_KEY / BINGX_API_SECRET', 'finished_at': now_iso()}
        store.put_kv('sync', dict(store.get_kv('sync', {}) or {}, **st))
        return st
    if not _try_start():
        return {'ok': True, 'running': True, 'message': '已經在同步中'}
    started = time.time()
    st = {}
    try:
        prev = store.get_kv('sync', {}) or {}
        st = dict(prev, running=True, started_at=now_iso(), error=None, full=bool(full))
        store.put_kv('sync', st)
        logger.info(f'[日誌] 開始同步（full={full}）')
        ex = _exchange()
        now_ms = int(time.time() * 1000)
        trades = store.list_trades()

        # 舊版（用成交明細組的）資料：沒補過任何東西的就清掉，避免和新資料重複
        removed = 0
        if prev.get('engine') != 'ph':
            for t in trades:
                if t.get('source') == 'api' and str(t.get('external_id', '')).startswith('fill:') and not _has_user_data(t):
                    store.delete_trade_hard(t['id'])
                    removed += 1
            trades = store.list_trades()
            full = True

        last_ms = prev.get('last_end_ms')
        start_ms = now_ms - BACKFILL_DAYS * DAY_MS if (full or not last_ms) else int(last_ms) - OVERLAP_MS
        open_api = [t for t in trades if t.get('source') == 'api' and t.get('status') == 'open' and not t.get('deleted_at')]
        for t in open_api:
            ms = _to_ms(t.get('open_time'))
            if ms:
                start_ms = min(start_ms, ms - 3600_000)

        live_rows = _data(ex.swapV2PrivateGetUserPositions({})) or []
        symbols = _income_symbols(ex, start_ms, now_ms)
        logger.info(f'[日誌] 找到幣種 {sorted(s for s in symbols if s)}，持倉 {len(live_rows)}')
        symbols |= {r.get('symbol') for r in live_rows if r.get('symbol')}
        symbols |= {(t.get('raw') or {}).get('symbol') for t in open_api}
        symbols.discard(None)

        by_ext = {t.get('external_id'): t for t in trades if t.get('external_id')}
        added = updated = 0
        sample = None
        counts = {}
        sl_found = sl_missing = 0
        for sym in sorted(symbols):
            recs = _position_history(ex, sym, start_ms, now_ms)
            counts[sym] = len(recs)
            maps = []
            for rec in recs:
                m = map_history(rec)
                if m['external_id'] in ('None', ''):
                    continue
                o = by_ext.get(m['external_id'])
                # 只有「還沒有停損、也沒手動填風險」的單才去找停損（新單，或完整重抓時）
                need = (not o or full) and not (o and (o.get('sl') not in (None, '') or o.get('risk_amount') not in (None, '')))
                maps.append((rec, m, need))
            if any(n for _, _, n in maps):
                try:
                    opens = [_to_ms(m['open_time']) for _, m, n in maps if n and m['open_time']]
                    closes = [_to_ms(m['close_time']) or now_ms for _, m, n in maps if n]
                    orders = _orders(ex, sym, min(opens) - 3 * DAY_MS, min(max(closes) + 60_000, now_ms)) if opens else []
                except Exception as e:
                    logger.warning(f'[日誌] {sym} 抓委託失敗，先不補停損：{e}')
                    orders = []
                for _, m, n in maps:
                    if n:
                        sl = _infer_sl(m, orders, now_ms)
                        if sl:
                            m['sl'] = sl
                            sl_found += 1
                        else:
                            sl_missing += 1
            for rec, m, _ in maps:
                sample = sample or rec
                old = by_ext.get(m['external_id'])
                if not old:
                    # 持倉中時記下的那筆（id 可能不同）：同幣、同方向、開倉時間差 3 分鐘內就併在一起
                    mo = _to_ms(m['open_time'])
                    for t in open_api:
                        to = _to_ms(t.get('open_time'))
                        if t['symbol'] == m['symbol'] and t['side'] == m['side'] and mo and to and abs(mo - to) <= 180_000:
                            store.update_trade(t['id'], m)
                            open_api.remove(t)
                            updated += 1
                            old = 'merged'
                            break
                    if old == 'merged':
                        continue
                store.upsert_api_trade(m)
                if old:
                    updated += 1
                else:
                    added += 1

        live_ids = set()
        for rec in live_rows:
            m = map_open(rec)
            if m['external_id'] in ('None', ''):
                continue
            live_ids.add(m['external_id'])
            old = by_ext.get(m['external_id'])
            if old and old.get('status') == 'closed':
                continue
            if old and old.get('open_time'):
                m.pop('open_time', None)
            store.upsert_api_trade(m)
            if old:
                updated += 1
            else:
                added += 1

        st = dict(st, ok=True, running=False, finished_at=now_iso(), last_end_ms=now_ms, engine='ph',
                  added=added, updated=updated, removed_old=removed, symbols=sorted(symbols), open_count=len(live_ids), history_counts=counts,
                  sl_found=sl_found, sl_missing=sl_missing,
                  seconds=round(time.time() - started, 1), error=None)
        if sample:
            st['sample'] = sample
        st['backfilled'] = True
        store.put_kv('sync', st)
        logger.info(f'[日誌] 同步完成：新增 {added}、更新 {updated}，幣種 {len(symbols)}')
        return st
    except Exception as e:
        logger.exception('[日誌] 同步失敗')
        st = dict(st, ok=False, running=False, finished_at=now_iso(), error=f'{type(e).__name__}: {e}'[:500])
        try:
            store.put_kv('sync', st)
        except Exception:
            logger.exception('[日誌] 寫入同步狀態失敗')
        return st
    finally:
        _finish()


def debug_probe(symbol='BTC-USDT', days=30):
    """除錯用：直接回傳交易所的原始回應（不含金鑰）。"""
    ex = _exchange()
    now = int(time.time() * 1000)
    start = now - days * DAY_MS
    out = {}
    calls = {
        'positionHistory': lambda: ex.swapV1PrivateGetTradePositionHistory({'symbol': symbol, 'startTs': start, 'endTs': now}),
        'fillHistory': lambda: ex.swapV2PrivateGetTradeFillHistory({'symbol': symbol, 'startTs': start, 'endTs': now}),
        'income': lambda: ex.swapV2PrivateGetUserIncome({'symbol': symbol, 'startTime': start, 'endTime': now, 'limit': 20}),
        'positions': lambda: ex.swapV2PrivateGetUserPositions({}),
        'allOrders': lambda: ex.swapV2PrivateGetTradeAllOrders(
            {'symbol': symbol, 'startTime': now - 7 * DAY_MS, 'endTime': now, 'limit': 50}),
        'ph_paged': lambda: ex.swapV1PrivateGetTradePositionHistory(
            {'symbol': symbol, 'startTs': start, 'endTs': now, 'pageIndex': 1, 'pageSize': 100}),
        'ph_older30': lambda: ex.swapV1PrivateGetTradePositionHistory(
            {'symbol': symbol, 'startTs': start - 30 * DAY_MS, 'endTs': start}),
        'ph_90': lambda: ex.swapV1PrivateGetTradePositionHistory(
            {'symbol': symbol, 'startTs': now - 90 * DAY_MS, 'endTs': now}),
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
