"""
SQLite 資料庫模組。
用途：
1. 儲存偵測到的訊號歷史，讓網頁可以顯示
2. 記錄「這根K棒 + 這個幣 + 這個方向」是否已經處理過，避免重複發Telegram通知
3. 儲存每個幣種的「策略運算狀態」，讓掃描從「每次全部重算」
   改成「讀取上次狀態→只算新K棒→存回狀態」
4. 儲存「目前掃描中的幣種清單」，讓網頁可以顯示
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


def signal_already_recorded(symbol: str, direction: str, candle_time: int) -> bool:
    with _lock:
        conn = get_connection()
        row = conn.execute(
            'SELECT 1 FROM signals WHERE symbol = ? AND direction = ? AND candle_time = ?',
            (symbol, direction, candle_time)
        ).fetchone()
        conn.close()
        return row is not None


def record_signal(symbol: str, direction: str, entry_price: float, sl_price: float, tp_price: float, candle_time: int, detected_at: int):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                'INSERT INTO signals (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, status) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (symbol, direction, entry_price, sl_price, tp_price, candle_time, detected_at, 'open')
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


def get_recent_signals(limit: int = 100) -> list:
    with _lock:
        conn = get_connection()
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
    """把這次掃描實際使用的幣種清單存起來 (只留一筆，每次覆蓋)。"""
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
    """讀取目前存的掃描名單。回傳 (symbols_list, updated_at)，還沒有資料時回傳 ([], None)。"""
    with _lock:
        conn = get_connection()
        row = conn.execute('SELECT symbols_json, updated_at FROM scan_state WHERE id = 1').fetchone()
        conn.close()
        if row is None:
            return [], None
        return json.loads(row['symbols_json']), row['updated_at']
