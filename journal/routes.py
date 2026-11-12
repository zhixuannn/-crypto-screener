import os
import io
import csv
import hmac
import time
import uuid
import json
import logging
import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import (Blueprint, render_template, request, jsonify, session, redirect, url_for,
                   send_file, Response, abort)

from .store import get_store, USER_FIELDS, EXCHANGE_FIELDS, JSON_LIST_FIELDS, StoreError, now_iso, guess_ext
from . import bingx_sync, notify

logger = logging.getLogger(__name__)

bp = Blueprint('journal', __name__, url_prefix='/journal',
               template_folder='templates', static_folder='static', static_url_path='/static')

DEFAULT_SETTINGS = {
    'displayName': 'Zhixuan',
    'tagline': '今天也記得，只做計畫內的交易',
    'capital': 1000,
    'defaultRisk': 10,
    'makerFee': 0.02,
    'takerFee': 0.05,
    'colorMode': 'greenUp',
    'setups': ['雙訂單塊 掛單回踩', '雙訂單塊 突破', '量能策略', '其他'],
    # dir: long / short / both ；color: 分類顏色
    'conditions': [
        {'name': 'CHoCH', 'dir': 'both', 'color': 'blue'},
        {'name': 'FVG', 'dir': 'both', 'color': 'blue'},
        {'name': 'BOS', 'dir': 'both', 'color': 'blue'},
        {'name': '訂單塊', 'dir': 'both', 'color': 'blue'},
        {'name': '3+1做多', 'dir': 'long', 'color': 'green'},
        {'name': '3+1做空', 'dir': 'short', 'color': 'red'},
        {'name': '日內偏見看多', 'dir': 'long', 'color': 'green'},
        {'name': '日內偏見看空', 'dir': 'short', 'color': 'red'},
        {'name': '8-24點時段', 'dir': 'both', 'color': 'purple'},
        {'name': '5M進場', 'dir': 'both', 'color': 'yellow'},
        {'name': '15M進場', 'dir': 'both', 'color': 'yellow'},
    ],
    'emotions': [
        {'name': '冷靜', 'tone': 'good'}, {'name': '心情好', 'tone': 'good'},
        {'name': '猶豫', 'tone': 'warn'}, {'name': 'FOMO怕錯過', 'tone': 'bad'},
        {'name': '想追回虧損', 'tone': 'bad'}, {'name': '心情差', 'tone': 'bad'},
    ],
    'mistakes': ['太早進場', '沒等確認', '追單', '提早出場', '亂移停損', '倉位太大', '沒照計畫', '重複進場'],
    'benchmarks': [
        {'setup': '雙訂單塊 掛單回踩', 'win': 52, 'pf': 1.0},
        {'setup': '雙訂單塊 突破', 'win': 48, 'pf': 0.98},
        {'setup': '量能策略', 'win': 51, 'pf': 1.25},
    ],
    'requireShot': True,
}

_login_fail = {}


def _password():
    return os.environ.get('JOURNAL_PASSWORD', '')


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('journal_ok') or int(session.get('journal_ver') or 0) != notify.session_ver():
            if request.path.startswith('/journal/api/'):
                return jsonify({'error': 'login_required'}), 401
            return redirect(url_for('journal.login', next=request.path))
        return fn(*a, **kw)
    return wrapper


def _err(msg, code=400):
    return jsonify({'error': msg}), code


@bp.errorhandler(StoreError)
def _store_error(e):
    logger.error(f'[日誌] {e}')
    return jsonify({'error': str(e)}), 502


# ---------------------------------------------------------------- pages
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not _password():
        return render_template('journal/login.html', error='伺服器還沒設定 JOURNAL_PASSWORD，請到 Render 的 Environment 加上這個變數。', disabled=True)
    error = None
    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        fails = [t for t in _login_fail.get(ip, []) if time.time() - t < 600]
        if len(fails) >= 8:
            error = '嘗試太多次，請 10 分鐘後再試'
        elif notify.check_password(request.form.get('password', '')):
            session.permanent = True
            session['journal_ok'] = True
            session['journal_ver'] = notify.session_ver()
            _login_fail.pop(ip, None)
            nxt = request.args.get('next') or url_for('journal.app_page')
            if not nxt.startswith('/journal'):
                nxt = url_for('journal.app_page')
            return redirect(nxt)
        else:
            fails.append(time.time())
            _login_fail[ip] = fails
            error = '密碼不對'
    return render_template('journal/login.html', error=error, disabled=False)


@bp.route('/logout')
def logout():
    session.pop('journal_ok', None)
    return redirect(url_for('journal.login'))


@bp.route('/')
@login_required
def app_page():
    return render_template('journal/app.html', v=_asset_version())


def _asset_version():
    try:
        base = os.path.join(os.path.dirname(__file__), 'static')
        files = ('core.js', 'pages.js', 'analytics.js', 'perf.js', 'settings.js', 'journal.css')
        return str(int(max(os.path.getmtime(os.path.join(base, f)) for f in files)))
    except OSError:
        return '1'


# ---------------------------------------------------------------- data
def _settings():
    s = dict(DEFAULT_SETTINGS)
    s.update(get_store().get_kv('settings', {}) or {})
    return s


def _sync_status():
    st = dict(get_store().get_kv('sync', {}) or {})
    st['running'] = bingx_sync._sync_lock.locked()
    st['has_keys'] = bingx_sync.has_keys()
    st['interval_minutes'] = int(os.environ.get('JOURNAL_SYNC_MINUTES', '5'))
    st['backfill_days'] = bingx_sync.BACKFILL_DAYS
    return st


_pool = ThreadPoolExecutor(max_workers=4)


@bp.route('/api/bootstrap')
@login_required
def api_bootstrap():
    store = get_store()
    # 四個查詢同時送出（伺服器在美國、資料庫在新加坡，一個一個問會慢很多）
    f_trades = _pool.submit(store.list_trades, exclude_source='paper')
    f_reviews = _pool.submit(store.list_reviews)
    f_settings = _pool.submit(_settings)
    f_sync = _pool.submit(_sync_status)
    f_extra = _pool.submit(lambda: {'notify': notify.public_cfg(), 'last_backup': notify.last_backup(), 'auth': notify.auth_info()})
    sync = f_sync.result()
    try:
        last = sync.get('last_end_ms')
        if sync.get('has_keys') and not sync.get('running') and (not last or time.time() * 1000 - float(last) > 5 * 60 * 1000):
            bingx_sync.sync_in_background()
    except Exception:
        logger.exception('[日誌] 背景同步啟動失敗')
    return jsonify({
        'trades': f_trades.result(),
        'reviews': f_reviews.result(),
        'settings': f_settings.result(),
        'defaults': DEFAULT_SETTINGS,
        'sync': sync,
        'store': store.kind,
        'ai': bool(os.environ.get('ANTHROPIC_API_KEY')),
        'about': _about(store),
        **f_extra.result(),
    })


APP_VERSION = '1.2.0'


def _about(store):
    v = _asset_version()
    try:
        updated = datetime.datetime.fromtimestamp(int(v), notify.TW).isoformat(timespec='minutes')
    except (ValueError, OSError):
        updated = None
    return {'version': APP_VERSION, 'commit': (os.environ.get('RENDER_GIT_COMMIT') or '')[:7] or None,
            'updated': updated, 'store': store.kind}


@bp.route('/api/debug-bingx')
@login_required
def api_debug_bingx():
    if not bingx_sync.has_keys():
        return _err('還沒設定 BingX API 金鑰')
    symbol = request.args.get('symbol', 'BTC-USDT')
    days = min(int(request.args.get('days', '7') or 7), 30)
    return jsonify(bingx_sync.debug_probe(symbol, days))


def _num(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clean(data, allowed):
    out = {}
    for k, v in (data or {}).items():
        if k not in allowed:
            continue
        if k in JSON_LIST_FIELDS:
            v = [x for x in (v or []) if x not in (None, '')] if isinstance(v, list) else []
            if k == 'tps':
                v = [_num(x) for x in v if _num(x) is not None][:5]
            else:
                v = [str(x)[:500] for x in v][:50]
        elif k in ('sl', 'risk_amount', 'entry', 'exit', 'qty', 'leverage', 'pnl', 'gross_pnl', 'fee', 'funding'):
            v = _num(v)
        elif k == 'followed_rules':
            v = None if v is None or v == '' else bool(v)
        elif k == 'side':
            v = 'short' if v == 'short' else 'long'
        elif k == 'status':
            v = 'open' if v == 'open' else 'closed'
        elif k in ('open_time', 'close_time'):
            v = v or None
        elif isinstance(v, str):
            v = v[:5000]
        out[k] = v
    return out


@bp.route('/api/trades', methods=['POST'])
@login_required
def api_create():
    data = _clean(request.json, USER_FIELDS | EXCHANGE_FIELDS)
    if not data.get('symbol'):
        return _err('請選擇或輸入幣種')
    data['symbol'] = data['symbol'].upper().replace('-', '').replace('/', '')
    data.setdefault('side', 'long')
    data.setdefault('status', 'closed')
    data['source'] = 'csv' if (request.json or {}).get('source') == 'csv' else 'manual'
    return jsonify(get_store().insert_trade(data))


@bp.route('/api/trades/bulk', methods=['POST'])
@login_required
def api_bulk_create():
    rows = (request.json or {}).get('trades') or []
    store = get_store()
    created = 0
    for r in rows[:2000]:
        data = _clean(r, USER_FIELDS | EXCHANGE_FIELDS)
        if not data.get('symbol') or not data.get('open_time'):
            continue
        data['symbol'] = data['symbol'].upper().replace('-', '').replace('/', '')
        data['source'] = 'csv'
        store.insert_trade(data)
        created += 1
    return jsonify({'created': created})


@bp.route('/api/trades/<tid>', methods=['PATCH'])
@login_required
def api_update(tid):
    store = get_store()
    t = store.get_trade(tid)
    if not t:
        return _err('找不到這筆交易', 404)
    allowed = USER_FIELDS if t.get('source') == 'api' else USER_FIELDS | EXCHANGE_FIELDS
    data = _clean(request.json, allowed)
    if not data:
        return jsonify(t)
    return jsonify(store.update_trade(tid, data))


@bp.route('/api/trades/<tid>', methods=['DELETE'])
@login_required
def api_delete(tid):
    store = get_store()
    if request.args.get('hard') == '1':
        store.delete_trade_hard(tid)
        return jsonify({'ok': True})
    return jsonify(store.update_trade(tid, {'deleted_at': now_iso()}))


@bp.route('/api/trades/<tid>/restore', methods=['POST'])
@login_required
def api_restore(tid):
    return jsonify(get_store().update_trade(tid, {'deleted_at': None}))


@bp.route('/api/trades/batch', methods=['POST'])
@login_required
def api_batch():
    body = request.json or {}
    ids = body.get('ids') or []
    action = body.get('action')
    store = get_store()
    out = []
    for tid in ids[:500]:
        t = store.get_trade(tid)
        if not t:
            continue
        if action == 'delete':
            out.append(store.update_trade(tid, {'deleted_at': now_iso()}))
        elif action == 'add_tags':
            field = body.get('field')
            if field not in ('conditions', 'emotions', 'mistakes'):
                return _err('欄位不對')
            tags = [str(x) for x in body.get('tags') or []]
            merged = list(dict.fromkeys((t.get(field) or []) + tags))
            out.append(store.update_trade(tid, {field: merged}))
        elif action == 'set_setup':
            out.append(store.update_trade(tid, {'setup': str(body.get('setup') or '')[:200]}))
    return jsonify({'trades': out})


@bp.route('/api/reviews/<day>', methods=['PUT'])
@login_required
def api_review(day):
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        return _err('日期格式不對')
    get_store().put_review(day, str((request.json or {}).get('note', ''))[:20000])
    return jsonify({'ok': True})


@bp.route('/api/settings', methods=['PUT'])
@login_required
def api_settings():
    body = request.json or {}
    s = {k: body[k] for k in DEFAULT_SETTINGS if k in body}
    merged = dict(get_store().get_kv('settings', {}) or {})
    merged.update(s)
    get_store().put_kv('settings', merged)
    return jsonify(_settings())


@bp.route('/api/sync', methods=['POST'])
@login_required
def api_sync():
    if not bingx_sync.has_keys():
        return _err('還沒設定 BingX API 金鑰（BINGX_API_KEY / BINGX_API_SECRET）')
    full = bool((request.json or {}).get('full'))
    bingx_sync.sync_in_background(full=full)
    time.sleep(0.3)
    return jsonify(_sync_status())


@bp.route('/api/sync-status')
@login_required
def api_sync_status():
    return jsonify(_sync_status())


@bp.route('/api/paper')
@login_required
def api_paper():
    from . import paper
    rows = [t for t in get_store().list_trades(only_source='paper') if not t.get('deleted_at')]
    return jsonify({'trades': rows, 'risk': paper.PAPER_RISK})


@bp.route('/api/paper/settle', methods=['POST'])
@login_required
def api_paper_settle():
    from . import paper
    return jsonify(paper.settle_open())


@bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    f = request.files.get('file')
    if not f:
        return _err('沒有收到圖片')
    ctype = f.mimetype or 'image/png'
    if ctype not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
        return _err('只接受 PNG、JPG、WEBP、GIF')
    data = f.read()
    if len(data) > 20 * 1024 * 1024:
        return _err('圖片太大（上限 20MB）')
    path = f"{datetime.date.today():%Y/%m}/{uuid.uuid4().hex}{guess_ext(ctype, f.filename)}"
    get_store().upload(path, data, ctype)
    return jsonify({'path': path})


@bp.route('/shot/<path:p>')
@login_required
def shot(p):
    store = get_store()
    blob = store.get_blob(p)
    if blob:
        return send_file(io.BytesIO(blob[0]), mimetype=blob[1])
    url = store.shot_url(p)
    if not url:
        abort(404)
    return redirect(url)


@bp.route('/api/export.csv')
@login_required
def api_export():
    text, _n = notify.trades_csv()
    return Response(text, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=journal_{datetime.date.today()}.csv'})


@bp.route('/api/notify', methods=['GET', 'PUT'])
@login_required
def api_notify():
    if request.method == 'PUT':
        return jsonify(notify.save_cfg(request.json or {}))
    return jsonify(notify.public_cfg())


@bp.route('/api/notify/test', methods=['POST'])
@login_required
def api_notify_test():
    if not notify.telegram_ready():
        return _err('伺服器還沒設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID')
    ok = notify.send('這是一則測試通知，看到就代表日誌的通知設定好了 👍')
    return jsonify({'ok': ok}) if ok else _err('Telegram 沒有收到，請檢查機器人設定', 502)


@bp.route('/api/backup-email', methods=['POST'])
@login_required
def api_backup_email():
    body = request.json or {}
    to = (body.get('to') or notify.get_cfg().get('email_to') or '').strip()
    if body.get('to') is not None:
        notify.save_cfg({'email_to': to})
    ok, msg = notify.send_backup(to)
    return jsonify({'ok': True, 'message': msg, 'last_backup': notify.last_backup()}) if ok else _err(msg, 502)


@bp.route('/api/password', methods=['POST'])
@login_required
def api_password():
    body = request.json or {}
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    fails = [t for t in _login_fail.get('pw:' + ip, []) if time.time() - t < 600]
    if len(fails) >= 5:
        return _err('嘗試太多次，請 10 分鐘後再試', 429)
    ok, res = notify.change_password(body.get('old', ''), body.get('new', ''))
    if not ok:
        if res == '目前的密碼不對':
            _login_fail['pw:' + ip] = fails + [time.time()]
        return _err(res)
    session['journal_ver'] = res   # 這台繼續登入，其他裝置會被登出
    return jsonify({'ok': True, 'auth': notify.auth_info()})


@bp.route('/api/ai', methods=['POST'])
@login_required
def api_ai():
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        return _err('還沒設定 ANTHROPIC_API_KEY，所以 AI 復盤暫時不能用')
    prompt = str((request.json or {}).get('prompt', ''))[:60000]
    try:
        r = requests.post('https://api.anthropic.com/v1/messages', timeout=120, headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5'), 'max_tokens': 2000,
                  'messages': [{'role': 'user', 'content': prompt}]})
        if r.status_code >= 400:
            return _err(f'AI 服務回傳錯誤 {r.status_code}：{r.text[:200]}', 502)
        text = ''.join(b.get('text', '') for b in r.json().get('content', []) if b.get('type') == 'text')
        return jsonify({'text': text})
    except requests.RequestException as e:
        return _err(f'連不到 AI 服務：{e}', 502)
