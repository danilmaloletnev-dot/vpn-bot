import sqlite3
import time
from contextlib import contextmanager
from config import cfg


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_code TEXT,
                price_rub INTEGER,
                status TEXT DEFAULT 'pending',   -- pending / paid / cancelled
                created_at INTEGER,
                paid_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS vpn_keys (
                key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                user_id INTEGER,
                config_text TEXT,
                expires_at INTEGER,
                issued_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS key_pool (
                pool_id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_text TEXT,
                used INTEGER DEFAULT 0
            );
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_user(user_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username, int(time.time())),
        )


def create_order(user_id: int, plan_code: str, price_rub: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO orders (user_id, plan_code, price_rub, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, plan_code, price_rub, int(time.time())),
        )
        return cur.lastrowid


def get_order(order_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()


def mark_order_paid(order_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status='paid', paid_at=? WHERE order_id=?",
            (int(time.time()), order_id),
        )


def mark_order_cancelled(order_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE orders SET status='cancelled' WHERE order_id=?", (order_id,))


def pop_free_key() -> str | None:
    """Забирает один свободный конфиг из пула (если вы предзагружаете конфиги вручную)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM key_pool WHERE used=0 LIMIT 1").fetchone()
        if not row:
            return None
        conn.execute("UPDATE key_pool SET used=1 WHERE pool_id=?", (row["pool_id"],))
        return row["config_text"]


def add_keys_to_pool(configs: list[str]):
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO key_pool (config_text) VALUES (?)", [(c,) for c in configs]
        )


def issue_key(order_id: int, user_id: int, config_text: str, expires_at: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO vpn_keys (order_id, user_id, config_text, expires_at, issued_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, config_text, expires_at, int(time.time())),
        )


def get_user_keys(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM vpn_keys WHERE user_id=? ORDER BY issued_at DESC", (user_id,)
        ).fetchall()
