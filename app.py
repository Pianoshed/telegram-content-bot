import os
import fcntl
from pathlib import Path

from flask import Flask, render_template, jsonify, request
from config import SECRET_KEY
import database as db
import scheduler
import random_poster
from poster import test_connection
from content_fetcher import fetch_posts
import telegram_bot

app = Flask(__name__)
app.secret_key = SECRET_KEY

db.init_db()

# ---------------------------------------------------------------------------
# Guard against starting the background workers more than once.
#
# scheduler.start()/telegram_bot.start()/random_poster.start() run at
# import time. If this module gets imported by more than one OS process --
# e.g. Render running gunicorn with >1 worker, or Werkzeug's debug reloader
# spawning a watcher + child locally -- each process starts its own copy of
# every worker. That means N schedulers hitting the same SQLite file at
# once (WAL "database is locked"), N Telegram pollers fighting over
# getUpdates (409 Conflict), and duplicate posts.
#
# A simple advisory file lock ensures only the first process to grab it
# starts the workers. Every other process still serves HTTP requests
# normally -- it just skips starting the threads.
# ---------------------------------------------------------------------------

_LOCK_PATH = Path(os.environ.get("WORKER_LOCK_PATH", "/tmp/movie_bot_worker.lock"))
_lock_file = None


def _acquire_worker_lock() -> bool:
    global _lock_file
    _lock_file = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _lock_file.close()
        _lock_file = None
        return False
    # Keep the fd open for the lifetime of this process -- that's what
    # holds the lock. It's released automatically when the process exits
    # or crashes, so a restart never leaves it stuck.
    _lock_file.write(str(os.getpid()))
    _lock_file.flush()
    return True


if _acquire_worker_lock():
    scheduler.start()
    telegram_bot.start()
    random_poster.start()
else:
    app.logger.info(
        "Background workers not started in this process "
        "(another process already holds the worker lock)."
    )


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── Bot control ───────────────────────────────────────────────────────────────

@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    ok = telegram_bot.start()
    return jsonify({"ok": ok, "message": "Bot started" if ok else "Already running"})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    telegram_bot.stop()
    return jsonify({"ok": True, "message": "Bot stopped"})


# ─── Random poster control ─────────────────────────────────────────────────────

@app.route("/api/random-poster/start", methods=["POST"])
def api_random_poster_start():
    ok = random_poster.start()
    return jsonify({"ok": ok, "message": "Random poster started" if ok else "Already running"})


@app.route("/api/random-poster/stop", methods=["POST"])
def api_random_poster_stop():
    random_poster.stop()
    return jsonify({"ok": True, "message": "Random poster stopped"})


# ─── API ─────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    stats = db.get_stats()
    stats["scheduler_running"] = scheduler.is_running()
    stats["bot_running"] = telegram_bot.is_running()
    stats["random_poster_running"] = random_poster.is_running()
    return jsonify(stats)


@app.route("/api/logs")
def api_logs():
    logs = db.get_recent_logs(30)
    return jsonify(logs)


@app.route("/api/start", methods=["POST"])
def api_start():
    ok = scheduler.start()
    return jsonify({"ok": ok, "message": "Scheduler started" if ok else "Already running"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    scheduler.stop()
    return jsonify({"ok": True, "message": "Scheduler stopped"})


@app.route("/api/post-now", methods=["POST"])
def api_post_now():
    result = scheduler.post_now()
    return jsonify(result)


@app.route("/api/test-connection")
def api_test():
    result = test_connection()
    return jsonify(result)


@app.route("/api/preview-feed")
def api_preview():
    try:
        posts = fetch_posts(limit=5)
        return jsonify({"ok": True, "posts": posts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    # use_reloader=False: the reloader re-executes this whole module in a
    # second process, which would start a second set of workers even
    # locally. Not needed for a dashboard like this.
    app.run(debug=True, port=5000, use_reloader=False)