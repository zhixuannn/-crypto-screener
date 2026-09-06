"""
SQLite 資料庫模組。
用途：
1. 儲存偵測到的訊號歷史，讓網頁可以顯示
2. 記錄「這根K棒 + 這個幣 + 這個方向」是否已經處理過，避免重複發Telegram通知
   (正常情況下策略本身不會重複觸發同一根K棒的訊號，這裡是多一層保險，
    防止伺服器重啟、掃描時間重疊等意外狀況造成重複通知)
3. 【新增】儲存每個幣種的「策略運算狀態」，讓掃描從「每次全部重算」
   改成「讀取上次狀態→只算新K棒→存回狀態」，避免因為視窗長度有限
   導致跟 Pine Script 版本(擁有完整歷史記憶)判斷不一致的問題
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
                tp_price REAL,
                candle_time INTEGER NOT NULL,
                detected_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_at INTEGER,
                UNIQUE(symbol, direction, candle_time)
            )
        ''')
        # ---- 針對「舊版資料庫」做欄位遷移：如果表格是舊版建立的、缺欄位，這裡補上 ----
        for col_name, col_type in [
            ('tp_price', 'REAL'),
            ('status', "TEXT NOT NULL DEFAULT 'open'"),
            ('closed_at', 'INTEGER'),
        ]:
            try:
                conn.execute(f'ALTER TABLE signals ADD COLUMN {col_name} {col_type}')
            except sqlite3.OperationalError:
                pass  # 欄位已經存在，忽略

        # ---- 【新增】每個幣種的策略運算狀態 ----
        conn.execute('''
            CREATE TABLE IF NOT EXISTS symbol_state (
                symbol TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                last_candle_time INTEGER NOT NULL,
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
            pass  # 已經存在，忽略 (跟signal_already_recorded互相保護，避免race condition)
        finally:
            conn.close()


def get_open_signals() -> list:
    """取得所有『還沒結束(還沒碰到止盈或止損)』的訊號，用於後續追蹤。"""
    with _lock:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM signals WHERE status = 'open'"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]


def close_signal(signal_id: int, status: str, closed_at: int):
    """把某筆訊號標記為結束 (status = 'tp_hit' 或 'sl_hit')。"""
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
    """
    把 ccxt 的交易對格式 (例如 'BTC/USDT:USDT') 轉成 TradingView 嵌入圖表用的代碼
    (例如 'BINGX:BTCUSDT.P')。
    """
    base_quote = symbol.split(':')[0]        # 'BTC/USDT'
    compact = base_quote.replace('/', '')     # 'BTCUSDT'
    return f'BINGX:{compact}.P'


# ==================== 【新增】幣種策略狀態 ====================

def get_symbol_state(symbol: str):
    """讀取某個幣種目前存的策略狀態。回傳 (state_json_str, last_candle_time) 或 None (代表還沒有狀態，是新幣種)。"""
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
    """把某個幣種最新的策略狀態存回去 (不存在就新增，存在就覆蓋)。"""
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
