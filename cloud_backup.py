"""
訊號紀錄的雲端備份（Supabase）。

為什麼需要：Render 免費方案的硬碟是臨時的，每次重新部署或重開，signals.db 就會被清空。
做法：
  - 平常照樣用本機 SQLite（快），每次新增／更新訊號或 TV 警報時，在背景把那一筆同步存到 Supabase。
  - 網站開機時，先把 Supabase 裡的紀錄全部抓回 SQLite，紀錄就不會因為重新部署而消失。
  - Supabase 那邊只有一張表 screener_records：kind（signal / tv_alert）+ uid（這筆的唯一代號）+ data（整筆內容 JSON）。
沒有設定 SUPABASE_URL / SUPABASE_SERVICE_KEY 時，整個模組什麼都不做（跟以前一樣只存本機）。
"""

import json
import logging
import os
import queue
import threading
import time

import requests

logger = logging.getLogger(__name__)

TABLE = 'screener_records'
_url = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
_key = os.environ.get('SUPABASE_SERVICE_KEY', '').strip()
_q = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def enabled() -> bool:
    return bool(_url and _key)


def _headers(prefer=None):
    h = {'apikey': _key, 'Authorization': f'Bearer {_key}', 'Content-Type': 'application/json'}
    if prefer:
        h['Prefer'] = prefer
    return h


def signal_uid(row: dict) -> str:
    # 跟 SQLite 的 UNIQUE(symbol, direction, candle_time, strategy, timeframe) 一樣。
    # 舊的 3+1 5m 訊號維持原本的代號（雲端已經存的不會變成兩筆）；其他策略／週期在後面加上去，才不會互相蓋掉
    uid = f"{row['symbol']}|{row['direction']}|{row['candle_time']}"
    strat = row.get('strategy') or 'xuan'
    tf = row.get('timeframe')
    if strat != 'xuan' or tf not in (None, '5m'):
        uid += f"|{strat}|{tf or ''}"
    return uid


def tv_uid(row: dict) -> str:
    return f"{row['received_at']}|{row['symbol']}|{row['strategy']}|{row['timeframe']}|{row['direction']}"


def _clean(row: dict) -> dict:
    d = dict(row)
    d.pop('id', None)   # 本機流水號不存，抓回來時讓 SQLite 自己重新編
    return d


# ---------------------------------------------------------------- 寫入（背景執行，不拖慢掃描）
def push(kind: str, rows: list):
    if not enabled() or not rows:
        return
    items = []
    for r in rows:
        r = dict(r)
        uid = signal_uid(r) if kind == 'signal' else tv_uid(r)
        items.append({'kind': kind, 'uid': uid, 'data': _clean(r)})
    _ensure_worker()
    _q.put(items)


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name='cloud-backup', daemon=True)
            _worker.start()


def _run():
    sess = requests.Session()
    while True:
        items = _q.get()
        # 把排隊中的一起送，減少連線次數；同一筆只留最新的內容
        batch = {(i['kind'], i['uid']): i for i in items}
        try:
            while True:
                for i in _q.get_nowait():
                    batch[(i['kind'], i['uid'])] = i
        except queue.Empty:
            pass
        body = [dict(i, updated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())) for i in batch.values()]
        for attempt in range(5):
            try:
                r = sess.post(f'{_url}/rest/v1/{TABLE}', params={'on_conflict': 'kind,uid'},
                              headers=_headers('resolution=merge-duplicates,return=minimal'),
                              data=json.dumps(body), timeout=20)
                if r.status_code < 300:
                    break
                logger.warning(f'[雲端備份] 寫入失敗 {r.status_code}: {r.text[:200]}')
            except Exception as e:
                logger.warning(f'[雲端備份] 寫入失敗: {e}')
            time.sleep(min(60, 5 * (attempt + 1)))
        else:
            logger.error(f'[雲端備份] 放棄這批 {len(body)} 筆（之後同一筆有更新時會再送一次）')


# ---------------------------------------------------------------- 開機時抓回來
def fetch_all(kind: str) -> list:
    out, offset, page = [], 0, 1000
    while True:
        r = requests.get(f'{_url}/rest/v1/{TABLE}', headers=_headers(),
                         params={'select': 'data', 'kind': f'eq.{kind}', 'order': 'uid', 'limit': page, 'offset': offset},
                         timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f'Supabase {r.status_code}: {r.text[:200]}')
        rows = r.json() or []
        out.extend(x['data'] for x in rows)
        if len(rows) < page:
            return out
        offset += page
