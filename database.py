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
            CREATE TABLE IF NOT EXISTS scan_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                symbols_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

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
                   candle_time: int, detected_at: int, strategy: str = 'xuan', timeframe: str = None):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                'INSERT INTO signals (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, status, strategy, timeframe) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, 'open', strategy, timeframe)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()


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
    query = "SELECT * FROM signals WHERE status IN ('tp_hit', 'sl_hit')"
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

    with _lock:
        conn = get_connection()
        rows = conn.execute(query, params).fetchall()
        conn.close()

    if not rows:
        return {'total': 0, 'win_rate': 0.0, 'total_r': 0.0}, []

    by_symbol = {}
    total_r = 0.0
    wins = 0

    for r in rows:
        r_mult = _row_r_multiple(r)
        is_win = r['status'] == 'tp_hit'
        total_r += r_mult
        if is_win:
            wins += 1

        sym = r['symbol']
        if sym not in by_symbol:
            by_symbol[sym] = {'total': 0, 'wins': 0, 'r': 0.0}
        by_symbol[sym]['total'] += 1
        by_symbol[sym]['wins'] += 1 if is_win else 0
        by_symbol[sym]['r'] += r_mult

    total = len(rows)
    overall = {
        'total': total,
        'win_rate': (wins / total * 100) if total else 0.0,
        'total_r': total_r,
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
