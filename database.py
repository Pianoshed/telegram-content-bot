import sqlite3
import json
from contextlib import closing
from datetime import date
from config import DATABASE_PATH


# ---------------------------------------------------------------------------
# SQLite connection management
# ---------------------------------------------------------------------------

def _connect():
    """Create a fresh SQLite connection.

    Every database operation gets its own connection. This is important
    because the scheduler, Telegram bot, random poster and Flask requests
    may run concurrently in different threads.
    """
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
        isolation_level=None,  # Explicit transactions only when needed.
    )
    conn.row_factory = sqlite3.Row

    # Do not change journal_mode on every request. WAL is initialized once
    # by init_db(). busy_timeout helps concurrent readers/writers wait safely.
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn():
    """Return a configured database connection."""
    return _connect()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Return True when a column already exists."""
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return any(row["name"] == column_name for row in rows)


# ---------------------------------------------------------------------------
# Initialization / migrations
# ---------------------------------------------------------------------------

def init_db():
    """Create the database schema and run safe one-time migrations.

    WAL is configured here, once, rather than every time a connection opens.
    """
    with closing(_connect()) as conn:
        # WAL can fail on a genuinely corrupted database. Do not hide that
        # error: deployment should stop rather than silently continue.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        conn.execute("BEGIN IMMEDIATE")
        try:
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
                    status TEXT,
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
                    source TEXT,
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

            # SQLite does not support ADD COLUMN IF NOT EXISTS.
            # Check first instead of swallowing every OperationalError.
            if not _column_exists(conn, "posted_items", "content_json"):
                conn.execute(
                    "ALTER TABLE posted_items ADD COLUMN content_json TEXT"
                )

            if not _column_exists(conn, "posted_items", "last_reposted_at"):
                conn.execute(
                    "ALTER TABLE posted_items "
                    "ADD COLUMN last_reposted_at TIMESTAMP"
                )

            conn.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) "
                "VALUES ('running', '0')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) "
                "VALUES ('total_posted', '0')"
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Posted items
# ---------------------------------------------------------------------------

def is_already_posted(link: str) -> bool:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM posted_items WHERE link = ? LIMIT 1",
            (link,),
        ).fetchone()
        return row is not None


def mark_posted(link: str, title: str, content: dict | None = None):
    """Store a posted item and increment the total-posted counter."""
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                """
                INSERT OR IGNORE INTO posted_items
                    (link, title, content_json)
                VALUES (?, ?, ?)
                """,
                (
                    link,
                    title,
                    json.dumps(content, ensure_ascii=False)
                    if content is not None else None,
                ),
            )

            # Only increment when a new row was actually inserted.
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                conn.execute(
                    """
                    UPDATE bot_settings
                    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
                    WHERE key = 'total_posted'
                    """
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Post logs
# ---------------------------------------------------------------------------

def log_post(title: str, link: str, status: str, message: str = ""):
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO post_log (title, link, status, message)
                VALUES (?, ?, ?, ?)
                """,
                (title, link, status, message),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_recent_logs(limit: int = 20):
    limit = max(1, min(int(limit), 500))

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM post_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------

def get_daily_post_count():
    with closing(get_conn()) as conn:
        return _get_daily_post_count(conn)


def _get_daily_post_count(conn) -> int:
    today = date.today().isoformat()

    stored_date = conn.execute(
        "SELECT value FROM bot_settings WHERE key = 'posts_today_date'"
    ).fetchone()

    if not stored_date or stored_date["value"] != today:
        return 0

    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key = 'posts_today_count'"
    ).fetchone()

    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def get_stats():
    """Return all dashboard statistics using one database connection."""
    with closing(get_conn()) as conn:
        total_row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'total_posted'"
        ).fetchone()

        success = conn.execute(
            "SELECT COUNT(*) AS c FROM post_log WHERE status = 'success'"
        ).fetchone()["c"]

        errors = conn.execute(
            "SELECT COUNT(*) AS c FROM post_log WHERE status = 'error'"
        ).fetchone()["c"]

        running_row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'running'"
        ).fetchone()

        members_joined = conn.execute(
            "SELECT COUNT(*) AS c FROM member_joins"
        ).fetchone()["c"]

        conversations = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations"
        ).fetchone()["c"]

        try:
            total_posted = int(total_row["value"]) if total_row else 0
        except (TypeError, ValueError):
            total_posted = 0

        running = bool(
            running_row and running_row["value"] == "1"
        )

        return {
            "total_posted": total_posted,
            "success": success,
            "errors": errors,
            "running": running,
            "members_joined": members_joined,
            "conversations": conversations,
            "posts_today": _get_daily_post_count(conn),
        }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def set_setting(key: str, value: str):
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO bot_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Conversation / engagement tracking
# ---------------------------------------------------------------------------

def log_conversation(
    chat_id: int,
    user_id: int,
    message: str,
    reply: str,
    source: str,
):
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO conversations
                    (chat_id, user_id, message, reply, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, message, reply, source),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_conversation_history(
    chat_id: int,
    user_id: int,
    limit: int = 6,
):
    """Return the last exchanges in oldest-first Anthropic-style format."""
    limit = max(1, min(int(limit), 100))

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT message, reply
            FROM conversations
            WHERE chat_id = ? AND user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (chat_id, user_id, limit),
        ).fetchall()

    history = []
    for row in reversed(rows):
        history.append({
            "role": "user",
            "content": row["message"],
        })
        history.append({
            "role": "assistant",
            "content": row["reply"],
        })

    return history


def log_member_join(chat_id: int, user_id: int, name: str):
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO member_joins (chat_id, user_id, name)
                VALUES (?, ?, ?)
                """,
                (chat_id, user_id, name),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_members_joined_count(since_days: int = 7) -> int:
    since_days = max(0, int(since_days))

    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM member_joins
            WHERE joined_at >= datetime('now', ?)
            """,
            (f"-{since_days} days",),
        ).fetchone()

        return row["c"]


# ---------------------------------------------------------------------------
# Daily post cap / repost queue
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().isoformat()


def increment_daily_post_count():
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            today = _today_str()

            stored_date = conn.execute(
                """
                SELECT value
                FROM bot_settings
                WHERE key = 'posts_today_date'
                """
            ).fetchone()

            if not stored_date or stored_date["value"] != today:
                conn.execute(
                    """
                    INSERT INTO bot_settings (key, value)
                    VALUES ('posts_today_date', ?)
                    ON CONFLICT(key) DO UPDATE
                    SET value = excluded.value
                    """,
                    (today,),
                )

                conn.execute(
                    """
                    INSERT INTO bot_settings (key, value)
                    VALUES ('posts_today_count', '1')
                    ON CONFLICT(key) DO UPDATE
                    SET value = '1'
                    """
                )
            else:
                conn.execute(
                    """
                    INSERT INTO bot_settings (key, value)
                    VALUES ('posts_today_count', '1')
                    ON CONFLICT(key) DO UPDATE
                    SET value =
                        CAST(CAST(bot_settings.value AS INTEGER) + 1 AS TEXT)
                    """
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise


def get_repost_candidate(cooldown_days: int = 14):
    """Return the oldest post eligible for reposting."""
    cooldown_days = max(0, int(cooldown_days))

    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM posted_items
            WHERE last_reposted_at IS NULL
               OR last_reposted_at <= datetime('now', ?)
            ORDER BY COALESCE(last_reposted_at, posted_at) ASC, id ASC
            LIMIT 1
            """,
            (f"-{cooldown_days} days",),
        ).fetchone()

    if not row:
        return None

    data = dict(row)

    if data.get("content_json"):
        try:
            post = json.loads(data["content_json"])
            if isinstance(post, dict):
                post.setdefault("link", data["link"])
                post.setdefault("title", data["title"])
                return post
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    # Older records may not have content_json.
    return {
        "link": data["link"],
        "title": data["title"],
    }


def mark_reposted(link: str):
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE posted_items
                SET last_reposted_at = CURRENT_TIMESTAMP
                WHERE link = ?
                """,
                (link,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise