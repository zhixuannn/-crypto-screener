"""
SQLite 資料庫模組。
"""

import sqlite3
import os
import json
import threading

DB_PATH = os.environ.get('DATABASE_PATH', 'signals.db')
_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                sl_price REAL NOT NULL,
                tp_price REAL,
                candle_time INTEGER NOT NULL,
                detected_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_at INTEGER,
                UNIQUE(symbol, direction, candle_time)
            )
        ''')
        for col_name, col_type in [
            ('tp_price', 'REAL'),
            ('status', "TEXT NOT NULL DEFAULT 'open'"),
            ('closed_at', 'INTEGER'),
            ('strategy', "TEXT NOT NULL DEFAULT 'xuan'"),
            ('timeframe', 'TEXT'),
            ('oi_score', 'INTEGER'),
            ('cvd_score', 'INTEGER'),
            ('total_score', 'INTEGER'),
            ('score_note', 'TEXT'),
            ('score_max', 'INTEGER'),
            ('score_detail', 'TEXT'),
            ('warning', 'TEXT'),
            ('tv_confirmed', 'INTEGER NOT NULL DEFAULT 0'),
            ('source', 'TEXT'),
        ]:
            try:
                conn.execute(f'ALTER TABLE signals ADD COLUMN {col_name} {col_type}')
            except sqlite3.OperationalError:
                pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS symbol_state (
                symbol TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                last_candle_time INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS tv_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                received_at INTEGER NOT NULL,
                matched INTEGER NOT NULL DEFAULT 0,
                note TEXT
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS scan_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                symbols_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

        # 索引：讓『查未平倉、查統計、查重複』不用整張表掃，資料多了也快
        for idx_sql in (
            'CREATE INDEX IF NOT EXISTS idx_sig_strategy_status ON signals(strategy, status, detected_at)',
            'CREATE INDEX IF NOT EXISTS idx_sig_open_lookup ON signals(symbol, strategy, timeframe, status)',
            'CREATE INDEX IF NOT EXISTS idx_sig_detected ON signals(detected_at)',
            'CREATE INDEX IF NOT EXISTS idx_tv_received ON tv_alerts(received_at)',
        ):
            conn.execute(idx_sql)

        conn.commit()
        conn.close()


def signal_already_recorded(symbol: str, direction: str, candle_time: int, strategy: str = 'xuan', timeframe: str = None) -> bool:
    with _lock:
        conn = get_connection()
        row = conn.execute(
            'SELECT 1 FROM signals WHERE symbol = ? AND direction = ? AND candle_time = ? AND strategy = ? AND (timeframe = ? OR (timeframe IS NULL AND ? IS NULL))',
            (symbol, direction, candle_time, strategy, timeframe, timeframe)
        ).fetchone()
        conn.close()
        return row is not None


def has_open_signal(symbol: str, strategy: str = 'xuan', timeframe: str = None) -> bool:
    """檢查這個幣種+策略+時區，目前是否已經有一筆『還沒結束』的訊號，用來避免同一段行情被重複開單。"""
    with _lock:
        conn = get_connection()
        row = conn.execute(
            "SELECT 1 FROM signals WHERE symbol = ? AND strategy = ? AND (timeframe = ? OR (timeframe IS NULL AND ? IS NULL)) AND status = 'open'",
            (symbol, strategy, timeframe, timeframe)
        ).fetchone()
        conn.close()
        return row is not None


def record_signal(symbol: str, direction: str, entry_price: float, sl_price: float, tp_price: float,
                   candle_time: int, detected_at: int, strategy: str = 'xuan', timeframe: str = None,
                   score: dict = None, source: str = 'site'):
    """score 是 scoring.evaluate() 的結果 (oi_score/cvd_score/total/note)，沒有分數就傳 None。"""
    oi_score = score['oi_score'] if score else None
    cvd_score = score['cvd_score'] if score else None
    total_score = score['total'] if score else None
    score_note = score['note'] if score else None
    score_max = score.get('max', 40) if score else None
    score_detail = json.dumps(score.get('detail') or [], ensure_ascii=False) if score else None
    warning = score.get('warning') if score else None
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                'INSERT INTO signals (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, status, strategy, timeframe, '
                'oi_score, cvd_score, total_score, score_note, score_max, score_detail, warning, source) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, 'open', strategy, timeframe,
                 oi_score, cvd_score, total_score, score_note, score_max, score_detail, warning, source)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()


def record_tv_alert(symbol: str, strategy: str, timeframe: str, direction: str, received_at: int) -> int:
    with _lock:
        conn = get_connection()
        cur = conn.execute(
            'INSERT INTO tv_alerts (symbol, strategy, timeframe, direction, received_at) VALUES (?, ?, ?, ?, ?)',
            (symbol, strategy, timeframe, direction, received_at)
        )
        conn.commit()
        alert_id = cur.lastrowid
        conn.close()
        return alert_id


def update_tv_alert(alert_id: int, matched: bool, note: str = None):
    with _lock:
        conn = get_connection()
        conn.execute('UPDATE tv_alerts SET matched = ?, note = ? WHERE id = ?', (1 if matched else 0, note, alert_id))
        conn.commit()
        conn.close()


def get_recent_tv_alerts(limit: int = 50) -> list:
    with _lock:
        conn = get_connection()
        rows = conn.execute('SELECT * FROM tv_alerts ORDER BY received_at DESC LIMIT ?', (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def mark_tv_confirmed(symbol: str, strategy: str, timeframe: str, direction: str, since_ms: int) -> int:
    """把『最近一段時間內、同幣種同策略同週期同方向』的訊號標記成 TV 也確認過。回傳標記了幾筆。"""
    with _lock:
        conn = get_connection()
        cur = conn.execute(
            'UPDATE signals SET tv_confirmed = 1 WHERE symbol = ? AND strategy = ? AND direction = ? '
            'AND (timeframe = ? OR (timeframe IS NULL AND ? IS NULL)) AND detected_at >= ?',
            (symbol, strategy, direction, timeframe, timeframe, since_ms)
        )
        conn.commit()
        n = cur.rowcount
        conn.close()
        return n


def get_open_signals() -> list:
    with _lock:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM signals WHERE status = 'open'"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]


def close_signal(signal_id: int, status: str, closed_at: int):
    with _lock:
        conn = get_connection()
        conn.execute(
            'UPDATE signals SET status = ?, closed_at = ? WHERE id = ?',
            (status, closed_at, signal_id)
        )
        conn.commit()
        conn.close()


def get_recent_signals(limit: int = 100, strategy: str = None) -> list:
    with _lock:
        conn = get_connection()
        if strategy:
            rows = conn.execute(
                'SELECT * FROM signals WHERE strategy = ? ORDER BY detected_at DESC LIMIT ?', (strategy, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM signals ORDER BY detected_at DESC LIMIT ?', (limit,)
            ).fetchall()
        conn.close()
        return [dict(row) for row in rows]


def symbol_to_tradingview(symbol: str) -> str:
    base_quote = symbol.split(':')[0]
    compact = base_quote.replace('/', '')
    return f'BINGX:{compact}.P'


def get_symbol_state(symbol: str):
    with _lock:
        conn = get_connection()
        row = conn.execute(
            'SELECT state_json, last_candle_time FROM symbol_state WHERE symbol = ?',
            (symbol,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return row['state_json'], row['last_candle_time']


def save_symbol_state(symbol: str, state_json: str, last_candle_time: int, updated_at: int):
    with _lock:
        conn = get_connection()
        conn.execute('''
            INSERT INTO symbol_state (symbol, state_json, last_candle_time, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                state_json = excluded.state_json,
                last_candle_time = excluded.last_candle_time,
                updated_at = excluded.updated_at
        ''', (symbol, state_json, last_candle_time, updated_at))
        conn.commit()
        conn.close()


def save_scan_symbols(symbols: list, updated_at: int):
    with _lock:
        conn = get_connection()
        conn.execute('''
            INSERT INTO scan_state (id, symbols_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                symbols_json = excluded.symbols_json,
                updated_at = excluded.updated_at
        ''', (json.dumps(symbols), updated_at))
        conn.commit()
        conn.close()


def get_scan_symbols_cached():
    with _lock:
        conn = get_connection()
        row = conn.execute('SELECT symbols_json, updated_at FROM scan_state WHERE id = 1').fetchone()
        conn.close()
        if row is None:
            return [], None
        return json.loads(row['symbols_json']), row['updated_at']


def _row_r_multiple(r) -> float:
    entry = r['entry_price']
    sl = r['sl_price']
    tp = r['tp_price']
    direction = r['direction']
    is_win = r['status'] == 'tp_hit'
    exit_price = tp if is_win else sl
    if exit_price is None:
        return 0.0
    if direction == 'long':
        risk = entry - sl
        reward = exit_price - entry
    else:
        risk = sl - entry
        reward = entry - exit_price
    if risk == 0:
        return 0.0
    return reward / risk


def get_stats(start_ms: int = None, end_ms: int = None, strategy: str = None):
    # 只取算統計需要的欄位 (不抓很長的 score_detail 文字，比較快)
    query = ("SELECT symbol, direction, entry_price, sl_price, tp_price, status, total_score, score_max "
             "FROM signals WHERE status IN ('tp_hit', 'sl_hit')")
    params = []
    if strategy:
        query += " AND strategy = ?"
        params.append(strategy)
    if start_ms is not None:
        query += " AND detected_at >= ?"
        params.append(start_ms)
    if end_ms is not None:
        query += " AND detected_at <= ?"
        params.append(end_ms)

    query += " ORDER BY COALESCE(closed_at, detected_at) ASC, id ASC"

    with _lock:
        conn = get_connection()
        rows = conn.execute(query, params).fetchall()
        conn.close()

    if not rows:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0, 'total_r': 0.0,
                'curve': [], 'by_score': []}, []

    by_symbol = {}
    total_r = 0.0
    wins = 0
    curve = []
    buckets = {}   # 分數區間 -> {'total','wins','r'}

    for r in rows:
        r_mult = _row_r_multiple(r)
        is_win = r['status'] == 'tp_hit'
        total_r += r_mult
        curve.append(round(total_r, 3))
        if is_win:
            wins += 1

        ts = r['total_score']
        smax = r['score_max'] or 40
        if ts is None:
            label = '無分數'
        elif smax == 100:
            if ts >= 70:
                label = '70-100'
            elif ts >= 50:
                label = '50-69'
            elif ts >= 30:
                label = '30-49'
            else:
                label = '0-29'
        else:
            if ts >= 30:
                label = '30-40'
            elif ts >= 20:
                label = '20-29'
            elif ts >= 10:
                label = '10-19'
            else:
                label = '0-9'
        b = buckets.setdefault(label, {'total': 0, 'wins': 0, 'r': 0.0})
        b['total'] += 1
        b['wins'] += 1 if is_win else 0
        b['r'] += r_mult

        sym = r['symbol']
        if sym not in by_symbol:
            by_symbol[sym] = {'total': 0, 'wins': 0, 'r': 0.0}
        by_symbol[sym]['total'] += 1
        by_symbol[sym]['wins'] += 1 if is_win else 0
        by_symbol[sym]['r'] += r_mult

    total = len(rows)
    order = ['70-100', '50-69', '30-49', '0-29', '30-40', '20-29', '10-19', '0-9', '無分數']
    by_score = [
        {'label': k, 'total': buckets[k]['total'],
         'win_rate': buckets[k]['wins'] / buckets[k]['total'] * 100,
         'r': buckets[k]['r']}
        for k in order if k in buckets
    ]
    overall = {
        'total': total,
        'wins': wins,
        'losses': total - wins,
        'win_rate': (wins / total * 100) if total else 0.0,
        'total_r': total_r,
        'curve': curve[-300:],
        'by_score': by_score,
    }

    per_symbol = []
    for sym, d in by_symbol.items():
        per_symbol.append({
            'symbol': sym.split('/')[0],
            'total': d['total'],
            'win_rate': (d['wins'] / d['total'] * 100) if d['total'] else 0.0,
            'r': d['r'],
        })
    per_symbol.sort(key=lambda x: x['r'], reverse=True)

    return overall, per_symbol


def get_open_signal_for_symbol(symbol: str, strategy: str = 'xuan'):
    """這個幣目前有沒有未平倉訊號 (查幣功能用)，沒有回傳 None。"""
    with _lock:
        conn = get_connection()
        row = conn.execute(
            "SELECT symbol, direction, entry_price, sl_price, tp_price, detected_at, total_score, score_max "
            "FROM signals WHERE symbol = ? AND strategy = ? AND status = 'open' "
            "ORDER BY detected_at DESC LIMIT 1", (symbol, strategy)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
