"""
日誌的 Telegram 通知、Email 備份、密碼。

通知用掃描網站同一個 Telegram 機器人（TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID），訊息開頭標「【日誌】」。
通知設定存在 journal_kv 的 'notify'；密碼雜湊存在 'auth'。
"""

import os
import io
import csv
import json
import time
import base64
import hashlib
import logging
import datetime
import threading

import requests
from werkzeug.security import generate_password_hash, check_password_hash

from .store import get_store, JSON_LIST_FIELDS

logger = logging.getLogger(__name__)
TW = datetime.timezone(datetime.timedelta(hours=8))

NOTIFY_DEFAULTS = {
    'review_on': False, 'review_time': '23:00',          # 每日復盤提醒（預設關）
    'pending_on': False, 'pending_min': 5,               # 待補完超過幾筆就提醒（一天最多一次）
    'paper_on': True,                                    # 紙上單打到止盈／止損
    'sync_on': True,                                     # BingX 同步失敗（三小時最多一次）
    'email_to': '',                                      # 備份寄到哪
}


def tw_now():
    return datetime.datetime.now(TW)


# ---------------------------------------------------------------- 通知設定
def get_cfg():
    cfg = dict(NOTIFY_DEFAULTS)
    try:
        cfg.update({k: v for k, v in (get_store().get_kv('notify', {}) or {}).items()})
    except Exception:
        logger.exception('[通知] 讀設定失敗')
    return cfg


def save_cfg(body):
    cur = get_cfg()
    for k, d in NOTIFY_DEFAULTS.items():
        if k not in body:
            continue
        v = body[k]
        if isinstance(d, bool):
            v = bool(v)
        elif isinstance(d, int):
            try:
                v = max(1, min(500, int(v)))
            except (TypeError, ValueError):
                v = d
        elif k == 'review_time':
            v = str(v)[:5] if len(str(v)) >= 4 and ':' in str(v) else d
        else:
            v = str(v or '').strip()[:200]
        cur[k] = v
    get_store().put_kv('notify', cur)
    return public_cfg(cur)


def telegram_ready():
    return bool(os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))


def email_ready():
    return bool(os.environ.get('RESEND_API_KEY'))


def public_cfg(cfg=None):
    cfg = cfg or get_cfg()
    out = {k: cfg.get(k, d) for k, d in NOTIFY_DEFAULTS.items()}
    out['telegram_ready'] = telegram_ready()
    out['email_ready'] = email_ready()
    return out


def send(text):
    """發一則【日誌】通知到 Telegram。"""
    try:
        import notifier   # 掃描網站的模組（專案根目錄）
        return notifier.send_telegram_message('📓 <b>【日誌】</b>' + text)
    except Exception:
        logger.exception('[通知] Telegram 發送失敗')
        return False


def _mark(key, value):
    try:
        st = get_store().get_kv('notify_state', {}) or {}
        st[key] = value
        get_store().put_kv('notify_state', st)
    except Exception:
        logger.exception('[通知] 寫狀態失敗')


def _state():
    try:
        return get_store().get_kv('notify_state', {}) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------- 事件
def paper_closed(t, upd):
    """紙上單結算時呼叫。"""
    try:
        if not get_cfg().get('paper_on'):
            return
        raw = upd.get('raw') or {}
        win = raw.get('exit_reason') == 'tp'
        entry, sl = float(t['entry']), float(t['sl'])
        R = (float(upd['exit']) - entry) / abs(entry - sl) * (1 if t['side'] == 'long' else -1)
        side = '做多' if t['side'] == 'long' else '做空'
        origin = 'TV 警報' if (t.get('raw') or {}).get('origin') == 'tv' else '網站掃描'
        send(f"紙上驗證{'✅ 止盈' if win else '❌ 停損'}\n{t['symbol']} {side}（{origin}）\n"
             f"結果：{R:+.2f}R，{float(upd.get('pnl') or 0):+.2f} U")
    except Exception:
        logger.exception('[通知] 紙上單通知失敗')


def sync_failed(err):
    """BingX 同步失敗時呼叫，三小時最多通知一次。"""
    try:
        if not get_cfg().get('sync_on'):
            return
        last = float(_state().get('sync_fail_ts') or 0)
        if time.time() - last < 3 * 3600:
            return
        _mark('sync_fail_ts', time.time())
        send(f"BingX 同步失敗，交易紀錄可能沒更新。\n原因：{str(err)[:300]}\n（三小時內不會再提醒）")
    except Exception:
        logger.exception('[通知] 同步失敗通知失敗')


def _pending_count(settings):
    req_shot = settings.get('requireShot', True) is not False
    n = 0
    for t in get_store().list_trades(exclude_source='paper'):
        if t.get('deleted_at'):
            continue
        try:
            entry, sl = float(t.get('entry') or 0), float(t.get('sl') or 0)
        except (TypeError, ValueError):
            entry = sl = 0
        has_r = bool(t.get('risk_amount')) or (entry and sl and entry != sl)
        has_cond = bool(t.get('conditions'))
        has_shot = bool(t.get('shots')) or bool(t.get('tv_links'))
        if not has_r or not has_cond or (req_shot and not has_shot):
            n += 1
    return n


def tick():
    """排程每 5 分鐘跑一次：每日復盤提醒、待補完提醒。"""
    try:
        cfg = get_cfg()
        if not (cfg.get('review_on') or cfg.get('pending_on')):
            return
        now = tw_now()
        today = now.strftime('%Y-%m-%d')
        hh, mm = (cfg.get('review_time') or '23:00').split(':')[:2]
        due = now.hour * 60 + now.minute >= int(hh) * 60 + int(mm)
        if not due:
            return
        st = _state()
        store = get_store()
        if cfg.get('review_on') and st.get('review_day') != today:
            _mark('review_day', today)
            reviews = store.list_reviews()
            if not (reviews.get(today) or '').strip():
                n = sum(1 for t in store.list_trades(exclude_source='paper')
                        if not t.get('deleted_at') and _tw_day(t.get('open_time')) == today)
                base = (os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
                link = f"\n打開日曆點今天就能寫 👉 {base}/journal/#/calendar" if base else ''
                send(f"該復盤囉！今天開了 {n} 筆單，還沒寫今天的復盤。{link}")
        if cfg.get('pending_on') and st.get('pending_day') != today:
            _mark('pending_day', today)
            from .routes import _settings
            n = _pending_count(_settings())
            if n >= int(cfg.get('pending_min') or 5):
                send(f"有 {n} 筆交易還沒補完（止損、進場條件或盤面快照），記得找時間補一下。")
    except Exception:
        logger.exception('[通知] 定時檢查失敗')


def _tw_day(iso):
    if not iso:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        return d.astimezone(TW).strftime('%Y-%m-%d')
    except ValueError:
        return None


# ---------------------------------------------------------------- 匯出 / Email 備份
EXPORT_COLS = ['open_time', 'close_time', 'symbol', 'side', 'status', 'source', 'setup', 'order_type', 'entry', 'exit',
               'qty', 'leverage', 'sl', 'risk_amount', 'pnl', 'fee', 'conditions', 'emotions', 'mistakes',
               'followed_rules', 'reason', 'note', 'tv_links']


def trades_csv():
    trades = [t for t in get_store().list_trades(exclude_source='paper') if not t.get('deleted_at')]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLS)
    for t in sorted(trades, key=lambda x: x.get('open_time') or ''):
        w.writerow(['|'.join(map(str, t.get(c) or [])) if c in JSON_LIST_FIELDS else ('' if t.get(c) is None else t.get(c))
                    for c in EXPORT_COLS])
    return '﻿' + buf.getvalue(), len(trades)


def send_backup(to):
    """用 Resend 把 CSV＋設定＋復盤寄出去。回傳 (ok, 訊息)。"""
    key = os.environ.get('RESEND_API_KEY')
    if not key:
        return False, '還沒設定 RESEND_API_KEY（請到 Render 的 Environment 加上）'
    to = (to or '').strip()
    if '@' not in to:
        return False, '請先填收件信箱'
    from .routes import _settings
    store = get_store()
    csv_text, n = trades_csv()
    day = tw_now().strftime('%Y-%m-%d')
    extra = json.dumps({'settings': _settings(), 'reviews': store.list_reviews()}, ensure_ascii=False, indent=1)
    b64 = lambda s: base64.b64encode(s.encode('utf-8')).decode()
    body = {
        'from': os.environ.get('RESEND_FROM') or 'XUAN 交易日誌 <onboarding@resend.dev>',
        'to': [to],
        'subject': f'XUAN 交易日誌備份 {day}（{n} 筆）',
        'text': f'附件是 {day} 的交易日誌備份：\n- journal_{day}.csv：{n} 筆交易\n- journal_{day}_settings.json：設定和每日復盤\n',
        'attachments': [
            {'filename': f'journal_{day}.csv', 'content': b64(csv_text)},
            {'filename': f'journal_{day}_settings.json', 'content': b64(extra)},
        ],
    }
    try:
        r = requests.post('https://api.resend.com/emails', json=body,
                          headers={'Authorization': f'Bearer {key}'}, timeout=30)
    except requests.RequestException as e:
        return False, f'寄信失敗：{e}'
    if r.status_code >= 400:
        try:
            msg = r.json().get('message') or r.text
        except ValueError:
            msg = r.text
        return False, f'寄信失敗（{r.status_code}）：{str(msg)[:300]}'
    _mark('last_backup', {'at': tw_now().isoformat(timespec='minutes'), 'to': to, 'n': n})
    return True, f'已寄出 {n} 筆交易到 {to}'


def last_backup():
    return _state().get('last_backup')


# ---------------------------------------------------------------- 密碼
_auth_cache = {'at': 0, 'val': None}
_auth_lock = threading.Lock()


def _env_pw():
    return os.environ.get('JOURNAL_PASSWORD', '')


def _env_fp():
    return hashlib.sha256(('xj:' + _env_pw()).encode()).hexdigest()[:16]


def auth_state(force=False):
    """回傳 {'hash','ver','env_fp','changed_at'} 或 None（用 Render 的 JOURNAL_PASSWORD）。60 秒快取。"""
    with _auth_lock:
        if not force and time.time() - _auth_cache['at'] < 60:
            a = _auth_cache['val']
        else:
            try:
                a = get_store().get_kv('auth', None)
            except Exception:
                logger.exception('[密碼] 讀取失敗')
                a = _auth_cache['val']
            _auth_cache.update(at=time.time(), val=a)
    # Render 的 JOURNAL_PASSWORD 改過 → 視為重設密碼，回到用 Render 那組
    if a and a.get('hash') and a.get('env_fp') == _env_fp():
        return a
    return None


def session_ver():
    a = auth_state()
    return int(a.get('ver') or 0) if a else 0


def check_password(pw):
    a = auth_state()
    if a:
        return check_password_hash(a['hash'], pw or '')
    env = _env_pw()
    import hmac
    return bool(env) and hmac.compare_digest(pw or '', env)


def change_password(old, new):
    if not check_password(old):
        return False, '目前的密碼不對'
    new = new or ''
    if len(new) < 8:
        return False, '新密碼至少要 8 個字'
    if new == old:
        return False, '新密碼跟舊的一樣'
    cur = auth_state(force=True)
    ver = (int(cur.get('ver') or 0) if cur else session_ver()) + 1
    a = {'hash': generate_password_hash(new), 'ver': ver, 'env_fp': _env_fp(),
         'changed_at': tw_now().isoformat(timespec='minutes')}
    get_store().put_kv('auth', a)
    with _auth_lock:
        _auth_cache.update(at=time.time(), val=a)
    return True, ver


def auth_info():
    a = auth_state()
    return {'custom': bool(a), 'changed_at': a.get('changed_at') if a else None}
