import sqlite3
from config import DATABASE_PATH


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posted_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE NOT NULL,
                title TEXT,
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS post_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                link TEXT,
                status TEXT,        -- 'success' | 'error'
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # defaults
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings VALUES ('running', '0')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings VALUES ('total_posted', '0')"
        )
        conn.commit()


def is_already_posted(link: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM posted_items WHERE link = ?", (link,)
        ).fetchone()
        return row is not None


def mark_posted(link: str, title: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO posted_items (link, title) VALUES (?, ?)",
            (link, title),
        )
        conn.execute(
            "UPDATE bot_settings SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'total_posted'"
        )
        conn.commit()


def log_post(title: str, link: str, status: str, message: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO post_log (title, link, status, message) VALUES (?, ?, ?, ?)",
            (title, link, status, message),
        )
        conn.commit()


def get_recent_logs(limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM post_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats():
    with get_conn() as conn:
        total = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'total_posted'"
        ).fetchone()["value"]
        success = conn.execute(
            "SELECT COUNT(*) as c FROM post_log WHERE status = 'success'"
        ).fetchone()["c"]
        errors = conn.execute(
            "SELECT COUNT(*) as c FROM post_log WHERE status = 'error'"
        ).fetchone()["c"]
        running = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'running'"
        ).fetchone()["value"]
        return {
            "total_posted": int(total),
            "success": success,
            "errors": errors,
            "running": running == "1",
        }


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()