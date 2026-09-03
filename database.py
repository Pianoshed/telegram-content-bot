import sqlite3
import json
from contextlib import closing
from datetime import date

from config import DATABASE_PATH


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL mode lets readers and writers work concurrently instead of
    # blocking each other — matters now that the scheduler thread and the
    # bot's polling thread both hit this file at once.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with closing(get_conn()) as conn:
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

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT,
                reply TEXT,
                source TEXT,        -- 'faq' | 'ai'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS member_joins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_chat_user
                ON conversations (chat_id, user_id, created_at);
        """)

        # Migrations: add columns needed for reposting if they don't exist yet.
        # (SQLite has no "ADD COLUMN IF NOT EXISTS", so we try/except instead.)
        for ddl in (
            "ALTER TABLE posted_items ADD COLUMN content_json TEXT",
            "ALTER TABLE posted_items ADD COLUMN last_reposted_at TIMESTAMP",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists

        # defaults
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings VALUES ('running', '0')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings VALUES ('total_posted', '0')"
        )
        conn.commit()


def is_already_posted(link: str) -> bool:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM posted_items WHERE link = ?", (link,)
        ).fetchone()
        return row is not None


def mark_posted(link: str, title: str, content: dict | None = None):
    """content: the full post dict (as returned by fetch_posts), stored so
    it can be resurfaced later as a repost without re-fetching."""
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO posted_items (link, title, content_json) VALUES (?, ?, ?)",
            (link, title, json.dumps(content) if content is not None else None),
        )
        conn.execute(
            "UPDATE bot_settings SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'total_posted'"
        )
        conn.commit()


def log_post(title: str, link: str, status: str, message: str = ""):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO post_log (title, link, status, message) VALUES (?, ?, ?, ?)",
            (title, link, status, message),
        )
        conn.commit()


def get_recent_logs(limit: int = 20):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM post_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats():
    with closing(get_conn()) as conn:
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
        members_joined = conn.execute(
            "SELECT COUNT(*) as c FROM member_joins"
        ).fetchone()["c"]
        conversations = conn.execute(
            "SELECT COUNT(*) as c FROM conversations"
        ).fetchone()["c"]
        return {
            "total_posted": int(total),
            "success": success,
            "errors": errors,
            "running": running == "1",
            "members_joined": members_joined,
            "conversations": conversations,
            "posts_today": get_daily_post_count(),
        }


def set_setting(key: str, value: str):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


# ─── Conversation + engagement tracking (for telegram_bot.py) ────────────────

def log_conversation(chat_id: int, user_id: int, message: str, reply: str, source: str):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO conversations (chat_id, user_id, message, reply, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, message, reply, source),
        )
        conn.commit()


def get_conversation_history(chat_id: int, user_id: int, limit: int = 6):
    """Return the last `limit` exchanges as alternating user/assistant messages,
    oldest first, in the shape the Anthropic API expects."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT message, reply FROM conversations "
            "WHERE chat_id = ? AND user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (chat_id, user_id, limit),
        ).fetchall()
    history = []
    for row in reversed(rows):
        history.append({"role": "user", "content": row["message"]})
        history.append({"role": "assistant", "content": row["reply"]})
    return history


def log_member_join(chat_id: int, user_id: int, name: str):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO member_joins (chat_id, user_id, name) VALUES (?, ?, ?)",
            (chat_id, user_id, name),
        )
        conn.commit()


def get_members_joined_count(since_days: int = 7) -> int:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM member_joins "
            "WHERE joined_at >= datetime('now', ?)",
            (f"-{since_days} days",),
        ).fetchone()
        return row["c"]


# ─── Daily post cap + repost queue (for scheduler.py) ─────────────────────────

def _today_str() -> str:
    return date.today().isoformat()


def get_daily_post_count() -> int:
    with closing(get_conn()) as conn:
        stored_date = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'posts_today_date'"
        ).fetchone()
        if not stored_date or stored_date["value"] != _today_str():
            return 0  # new day, nothing posted yet
        row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'posts_today_count'"
        ).fetchone()
        return int(row["value"]) if row else 0


def increment_daily_post_count():
    with closing(get_conn()) as conn:
        today = _today_str()
        stored_date = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'posts_today_date'"
        ).fetchone()
        if not stored_date or stored_date["value"] != today:
            # first post of a new day — reset the counter
            conn.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('posts_today_date', ?)",
                (today,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('posts_today_count', '1')"
            )
        else:
            conn.execute(
                "UPDATE bot_settings SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                "WHERE key = 'posts_today_count'"
            )
        conn.commit()


def get_repost_candidate(cooldown_days: int = 14):
    """Return the oldest post that hasn't been (re)posted within
    `cooldown_days`, as a full post dict ready to hand to post_to_channel.
    None if nothing is eligible yet (e.g. queue is empty or too fresh)."""
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM posted_items "
            "WHERE last_reposted_at IS NULL "
            "   OR last_reposted_at <= datetime('now', ?) "
            "ORDER BY COALESCE(last_reposted_at, posted_at) ASC "
            "LIMIT 1",
            (f"-{cooldown_days} days",),
        ).fetchone()

    if not row:
        return None

    data = dict(row)
    if data.get("content_json"):
        try:
            post = json.loads(data["content_json"])
            post.setdefault("link", data["link"])
            post.setdefault("title", data["title"])
            return post
        except (TypeError, ValueError):
            pass

    # Older rows posted before content_json existed — best effort.
    return {"link": data["link"], "title": data["title"]}


def mark_reposted(link: str):
    with closing(get_conn()) as conn:
        conn.execute(
            "UPDATE posted_items SET last_reposted_at = CURRENT_TIMESTAMP WHERE link = ?",
            (link,),
        )
        conn.commit()