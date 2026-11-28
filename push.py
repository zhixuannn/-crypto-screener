"""
手機推播通知（Web Push）：網站關掉也收得到，像 App 一樣。

- 每台手機／電腦在「設定」頁開通知時，瀏覽器會給一組「訂閱」，連同它自己選的條件存起來：
    要不要收新訊號、要不要收止盈／止損、哪些策略（3+1／流動性）、哪些週期（5m／15m）、3+1 最低分數
- 訂閱和推播用的金鑰（VAPID）都存在 Supabase（screener_records），重新部署也不會不見；
  沒設定 Supabase 時只存在記憶體，重開就要重新開通知。
- 有新訊號或打到止盈止損時，在背景發給條件符合的裝置；裝置已經取消（回 404/410）就自動刪掉那筆訂閱。
"""

import base64
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import cloud_backup

logger = logging.getLogger(__name__)

CONTACT = 'mailto:screener@example.com'   # VAPID 規定要一個聯絡方式，隨便填一個就好
_lock = threading.Lock()
_subs = {}            # uid -> {'subscription': {...}, 'prefs': {...}}
_keys = None          # {'public': base64url, 'private_pem': str}
_loaded = False
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='push')

DEFAULT_PREFS = {'new': True, 'close': True, 'strategies': ['xuan', 'liq'], 'timeframes': ['5m', '15m'], 'min_score': 0}


# ---------------------------------------------------------------- Supabase 讀寫（跟訊號備份同一張表）
def _rest(method, params=None, body=None):
    if not cloud_backup.enabled():
        return None
    h = cloud_backup._headers('resolution=merge-duplicates,return=minimal' if method == 'POST' else None)
    r = requests.request(method, f'{cloud_backup._url}/rest/v1/{cloud_backup.TABLE}', headers=h,
                         params=params, data=json.dumps(body) if body is not None else None, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f'Supabase {r.status_code}: {r.text[:200]}')
    return r.json() if method == 'GET' else None


def _save_row(kind, uid, data):
    _rest('POST', {'on_conflict': 'kind,uid'},
          [{'kind': kind, 'uid': uid, 'data': data, 'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}])


def _delete_row(kind, uid):
    _rest('DELETE', {'kind': f'eq.{kind}', 'uid': f'eq.{uid}'})


# ---------------------------------------------------------------- 金鑰
def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def _new_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    return {'public': _b64url(pub), 'private_pem': pem}


def _load():
    """第一次用到時：從 Supabase 抓金鑰和所有訂閱；沒有金鑰就產生一組存回去。"""
    global _keys, _loaded
    with _lock:
        if _loaded:
            return
        keys = None
        try:
            rows = _rest('GET', {'select': 'data', 'kind': 'eq.vapid', 'uid': 'eq.keys'}) or []
            keys = rows[0]['data'] if rows else None
        except Exception as e:
            logger.warning(f'[推播] 讀金鑰失敗: {e}')
        if not keys:
            keys = _new_keys()
            try:
                _save_row('vapid', 'keys', keys)
            except Exception as e:
                logger.warning(f'[推播] 存金鑰失敗（重開後要重新開通知）: {e}')
        _keys = keys
        try:
            rows = _rest('GET', {'select': 'uid,data', 'kind': 'eq.push_sub', 'limit': '1000'}) or []
            for r in rows:
                _subs[r['uid']] = r['data']
        except Exception as e:
            logger.warning(f'[推播] 讀訂閱失敗: {e}')
        _loaded = True
        logger.info(f'[推播] 準備好了，目前 {len(_subs)} 個裝置有開通知')


def public_key() -> str:
    _load()
    return _keys['public']


# ---------------------------------------------------------------- 訂閱
def _uid(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:32]


def _clean_prefs(p) -> dict:
    p = p or {}
    # 沒給的欄位用預設值（全部都收）
    strategies = [s for s in p.get('strategies', DEFAULT_PREFS['strategies']) or [] if s in ('xuan', 'liq')]
    timeframes = [t for t in p.get('timeframes', DEFAULT_PREFS['timeframes']) or [] if t in ('5m', '15m')]
    try:
        min_score = max(0, min(100, int(p.get('min_score') or 0)))
    except (TypeError, ValueError):
        min_score = 0
    return {'new': bool(p.get('new', True)), 'close': bool(p.get('close', True)),
            'strategies': strategies, 'timeframes': timeframes, 'min_score': min_score}


def subscribe(subscription: dict, prefs: dict) -> dict:
    _load()
    endpoint = (subscription or {}).get('endpoint') or ''
    keys = (subscription or {}).get('keys') or {}
    if not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):
        raise ValueError('訂閱資料不完整')
    uid = _uid(endpoint)
    data = {'subscription': {'endpoint': endpoint, 'keys': {'p256dh': keys['p256dh'], 'auth': keys['auth']}},
            'prefs': _clean_prefs(prefs)}
    with _lock:
        _subs[uid] = data
    try:
        _save_row('push_sub', uid, data)
    except Exception as e:
        logger.warning(f'[推播] 存訂閱失敗: {e}')
    return data['prefs']


def unsubscribe(endpoint: str):
    _load()
    uid = _uid(endpoint or '')
    with _lock:
        _subs.pop(uid, None)
    try:
        _delete_row('push_sub', uid)
    except Exception as e:
        logger.warning(f'[推播] 刪訂閱失敗: {e}')


def get_prefs(endpoint: str):
    _load()
    d = _subs.get(_uid(endpoint or ''))
    return d['prefs'] if d else None


# ---------------------------------------------------------------- 發送
def _send_one(uid, data, payload):
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    try:
        vapid = Vapid.from_pem(_keys['private_pem'].encode())
        webpush(subscription_info=data['subscription'], data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=vapid, vapid_claims={'sub': CONTACT}, ttl=3600, timeout=10)
    except WebPushException as e:
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if code in (404, 410):   # 這台裝置已經取消通知或換了瀏覽器
            logger.info('[推播] 有一台裝置已失效，刪掉它的訂閱')
            with _lock:
                _subs.pop(uid, None)
            try:
                _delete_row('push_sub', uid)
            except Exception:
                pass
        else:
            logger.warning(f'[推播] 發送失敗 ({code}): {e}')
    except Exception as e:
        logger.warning(f'[推播] 發送失敗: {e}')


def _match(prefs, event, strategy, timeframe, score):
    if not prefs.get(event):
        return False
    if strategy not in prefs.get('strategies', []):
        return False
    if (timeframe or '5m') not in prefs.get('timeframes', []):
        return False
    if strategy == 'xuan' and prefs.get('min_score'):
        if score is None or score < prefs['min_score']:
            return False
    return True


def notify(event: str, strategy: str, timeframe: str, score, title: str, body: str):
    """event：'new'（新訊號）或 'close'（止盈／止損）。在背景發，不會拖慢掃描。"""
    try:
        _load()
    except Exception as e:
        logger.warning(f'[推播] 準備失敗: {e}')
        return
    with _lock:
        targets = [(uid, d) for uid, d in _subs.items() if _match(d.get('prefs') or {}, event, strategy, timeframe, score)]
    if not targets:
        return
    payload = {'title': title, 'body': body, 'url': '/', 'tag': f'{event}-{strategy}-{int(time.time())}'}
    for uid, d in targets:
        _pool.submit(_send_one, uid, d, payload)


def send_test(endpoint: str) -> bool:
    _load()
    uid = _uid(endpoint or '')
    d = _subs.get(uid)
    if not d:
        return False
    _send_one(uid, d, {'title': '訊號掃描', 'body': '測試通知：收到這則就代表推播設定成功了 ✓', 'url': '/', 'tag': 'test'})
    return True
