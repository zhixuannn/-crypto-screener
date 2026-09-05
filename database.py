"""
SQLite 資料庫模組。
用途：
1. 儲存偵測到的訊號歷史，讓網頁可以顯示
2. 記錄「這根K棒 + 這個幣 + 這個方向」是否已經處理過，避免重複發Telegram通知
   (正常情況下策略本身不會重複觸發同一根K棒的訊號，這裡是多一層保險，
    防止伺服器重啟、掃描時間重疊等意外狀況造成重複通知)
"""

import sqlite3
import os
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
                candle_time INTEGER NOT NULL,
                detected_at INTEGER NOT NULL,
                UNIQUE(symbol, direction, candle_time)
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


def record_signal(symbol: str, direction: str, entry_price: float, sl_price: float, candle_time: int, detected_at: int):
    with _lock:
        conn = get_connection()
        try:
            conn.execute(
                'INSERT INTO signals (symbol, direction, entry_price, sl_price, candle_time, detected_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (symbol, direction, entry_price, sl_price, candle_time, detected_at)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # 已經存在，忽略 (跟signal_already_recorded互相保護，避免race condition)
        finally:
            conn.close()


def get_recent_signals(limit: int = 100) -> list:
    with _lock:
        conn = get_connection()
        rows = conn.execute(
            'SELECT * FROM signals ORDER BY detected_at DESC LIMIT ?', (limit,)
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
