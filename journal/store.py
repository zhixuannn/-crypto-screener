"""
交易日誌的資料存取。
有設定 SUPABASE_URL / SUPABASE_SERVICE_KEY 就存到 Supabase；沒有就用記憶體（只適合本機測試，重開就不見）。
"""

import os
import json
import uuid
import logging
import datetime
import threading
import mimetypes

import requests

logger = logging.getLogger(__name__)

TRADE_TABLE = 'journal_trades'
REVIEW_TABLE = 'journal_reviews'
KV_TABLE = 'journal_kv'
BUCKET = 'journal-shots'

# 前端可以改的欄位（API 單另外鎖住交易所欄位）
USER_FIELDS = {
    'sl', 'tps', 'risk_amount', 'setup', 'order_type', 'conditions', 'emotions', 'mistakes',
    'followed_rules', 'rule_note', 'reason', 'note', 'shots', 'tv_links',
}
EXCHANGE_FIELDS = {
    'symbol', 'side', 'status', 'open_time', 'close_time', 'entry', 'exit', 'qty', 'leverage',
    'pnl', 'gross_pnl', 'fee', 'funding',
}
JSON_LIST_FIELDS = {'tps', 'conditions', 'emotions', 'mistakes', 'shots', 'tv_links'}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class StoreError(Exception):
    pass


# ----------------------------------------------------------------------------
class MemoryStore:
    kind = 'memory'

    def __init__(self):
        self._lock = threading.Lock()
        self.trades = {}
        self.reviews = {}
        self.kv = {}
        self.blobs = {}

    def list_trades(self):
        with self._lock:
            return [dict(t) for t in self.trades.values()]

    def get_trade(self, tid):
        with self._lock:
            t = self.trades.get(tid)
            return dict(t) if t else None

    def find_by_external(self, ext):
        with self._lock:
            for t in self.trades.values():
                if t.get('external_id') == ext:
                    return dict(t)
        return None

    def insert_trade(self, data):
        with self._lock:
            t = {k: ([] if k in JSON_LIST_FIELDS else None) for k in USER_FIELDS | EXCHANGE_FIELDS}
            t.update({'source': 'manual', 'external_id': None, 'raw': None, 'deleted_at': None})
            t.update(data)
            t['id'] = str(uuid.uuid4())
            t['created_at'] = t['updated_at'] = now_iso()
            self.trades[t['id']] = t
            return dict(t)

    def update_trade(self, tid, data):
        with self._lock:
            t = self.trades.get(tid)
            if not t:
                return None
            t.update(data)
            t['updated_at'] = now_iso()
            return dict(t)

    def upsert_api_trade(self, data):
        ext = data['external_id']
        existing = self.find_by_external(ext)
        if existing:
            return self.update_trade(existing['id'], data)
        return self.insert_trade(dict(data, source='api'))

    def delete_trade_hard(self, tid):
        with self._lock:
            self.trades.pop(tid, None)

    def list_reviews(self):
        with self._lock:
            return dict(self.reviews)

    def put_review(self, day, note):
        with self._lock:
            self.reviews[day] = note

    def get_kv(self, key, default=None):
        with self._lock:
            return json.loads(json.dumps(self.kv.get(key, default)))

    def put_kv(self, key, value):
        with self._lock:
            self.kv[key] = json.loads(json.dumps(value))

    def upload(self, path, data, content_type):
        self.blobs[path] = (data, content_type)
        return path

    def shot_url(self, path):
        return None  # 由 routes 直接回傳 bytes

    def get_blob(self, path):
        return self.blobs.get(path)


# ----------------------------------------------------------------------------
class SupabaseStore:
    kind = 'supabase'

    def __init__(self, url, key):
        self.url = url.rstrip('/')
        self.key = key
        self.s = requests.Session()
        self.s.headers.update({'apikey': key, 'Authorization': f'Bearer {key}'})

    # --- helpers
    def _rest(self, method, table, params=None, body=None, prefer=None):
        headers = {'Content-Type': 'application/json'}
        if prefer:
            headers['Prefer'] = prefer
        r = self.s.request(method, f'{self.url}/rest/v1/{table}', params=params,
                           data=json.dumps(body) if body is not None else None, headers=headers, timeout=20)
        if r.status_code >= 400:
            raise StoreError(f'Supabase {method} {table} {r.status_code}: {r.text[:300]}')
        if not r.text:
            return None
        return r.json()

    # --- trades
    def list_trades(self):
        out, offset, page = [], 0, 1000
        while True:
            rows = self._rest('GET', TRADE_TABLE, params={
                'select': '*', 'order': 'open_time.desc.nullslast', 'limit': page, 'offset': offset})
            out.extend(rows or [])
            if not rows or len(rows) < page:
                break
            offset += page
        return out

    def get_trade(self, tid):
        rows = self._rest('GET', TRADE_TABLE, params={'select': '*', 'id': f'eq.{tid}'})
        return rows[0] if rows else None

    def find_by_external(self, ext):
        rows = self._rest('GET', TRADE_TABLE, params={'select': '*', 'external_id': f'eq.{ext}'})
        return rows[0] if rows else None

    def insert_trade(self, data):
        rows = self._rest('POST', TRADE_TABLE, body=data, prefer='return=representation')
        return rows[0] if rows else None

    def update_trade(self, tid, data):
        data = dict(data, updated_at=now_iso())
        rows = self._rest('PATCH', TRADE_TABLE, params={'id': f'eq.{tid}'}, body=data,
                          prefer='return=representation')
        return rows[0] if rows else None

    def upsert_api_trade(self, data):
        # merge-duplicates 只會更新這次送出的欄位，所以你補的止損、條件、心得不會被蓋掉
        body = dict(data, source='api', updated_at=now_iso())
        rows = self._rest('POST', TRADE_TABLE, params={'on_conflict': 'external_id'}, body=body,
                          prefer='resolution=merge-duplicates,return=representation')
        return rows[0] if rows else None

    def delete_trade_hard(self, tid):
        self._rest('DELETE', TRADE_TABLE, params={'id': f'eq.{tid}'})

    # --- reviews
    def list_reviews(self):
        rows = self._rest('GET', REVIEW_TABLE, params={'select': 'day,note'}) or []
        return {r['day']: r['note'] for r in rows}

    def put_review(self, day, note):
        self._rest('POST', REVIEW_TABLE, params={'on_conflict': 'day'},
                   body={'day': day, 'note': note, 'updated_at': now_iso()},
                   prefer='resolution=merge-duplicates')

    # --- key/value
    def get_kv(self, key, default=None):
        rows = self._rest('GET', KV_TABLE, params={'select': 'value', 'key': f'eq.{key}'})
        return rows[0]['value'] if rows else default

    def put_kv(self, key, value):
        self._rest('POST', KV_TABLE, params={'on_conflict': 'key'},
                   body={'key': key, 'value': value, 'updated_at': now_iso()},
                   prefer='resolution=merge-duplicates')

    # --- storage
    def upload(self, path, data, content_type):
        r = self.s.post(f'{self.url}/storage/v1/object/{BUCKET}/{path}', data=data,
                        headers={'Content-Type': content_type, 'x-upsert': 'true'}, timeout=60)
        if r.status_code >= 400:
            raise StoreError(f'截圖上傳失敗 {r.status_code}: {r.text[:200]}')
        return path

    def shot_url(self, path):
        r = self.s.post(f'{self.url}/storage/v1/object/sign/{BUCKET}/{path}',
                        json={'expiresIn': 3600}, timeout=20)
        if r.status_code >= 400:
            raise StoreError(f'截圖連結失敗 {r.status_code}: {r.text[:200]}')
        signed = r.json().get('signedURL') or r.json().get('signedUrl')
        return f'{self.url}/storage/v1{signed}'

    def get_blob(self, path):
        return None


_store = None
_store_lock = threading.Lock()


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            url = os.environ.get('SUPABASE_URL', '').strip()
            key = os.environ.get('SUPABASE_SERVICE_KEY', '').strip()
            if url and key:
                _store = SupabaseStore(url, key)
                logger.info('[日誌] 使用 Supabase 存資料')
            else:
                _store = MemoryStore()
                logger.warning('[日誌] 沒有設定 SUPABASE_URL / SUPABASE_SERVICE_KEY，資料只存在記憶體，重開就會不見')
        return _store


def guess_ext(content_type, filename=''):
    ext = mimetypes.guess_extension(content_type or '') or os.path.splitext(filename)[1] or '.png'
    return '.jpg' if ext in ('.jpe', '.jpeg') else ext
