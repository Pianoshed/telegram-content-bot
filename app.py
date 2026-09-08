import logging
import os
import threading

from flask import Flask, render_template, jsonify

from config import SECRET_KEY
import database as db
import scheduler
import random_poster
from poster import test_connection
from content_fetcher import fetch_posts
import telegram_bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = SECRET_KEY

db.init_db()

# Background workers only start when explicitly told to. The web process
# NEVER starts them — that job belongs to worker.py. This prevents duplicate
# bots/schedulers when Gunicorn boots multiple workers or the dev reloader
# spawns a second process.
if os.environ.get("RUN_WORKERS") == "1":
    for name, start_fn in (
        ("scheduler", scheduler.start),
        ("telegram_bot", telegram_bot.start),
        ("random_poster", random_poster.start),
    ):
        try:
            start_fn()
        except Exception:
            # One broken worker must not take down the dashboard
            log.exception("Failed to start %s on boot", name)


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── Bot control ─────────────────────────────────────────────────────────────

@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    ok = telegram_bot.start()
    return jsonify({"ok": ok, "message": "Bot started" if ok else "Already running"})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    telegram_bot.stop()
    return jsonify({"ok": True, "message": "Bot stopped"})


# ─── Random poster control ───────────────────────────────────────────────────

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
    return jsonify(db.get_recent_logs(30))


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
    # Run the post in a background thread so a slow poster can't hang the
    # HTTP request (which would trip Render's timeout and return a 502).
    result = {}

    def _do_post():
        result.update(scheduler.post_now())

    t = threading.Thread(target=_do_post, daemon=True)
    t.start()
    t.join(timeout=25)  # give it 25s, then return "accepted" anyway

    if result:
        return jsonify(result)
    return jsonify({"ok": True, "message": "Post triggered in background"})


@app.route("/api/test-connection", methods=["POST"])
def api_test():
    return jsonify(test_connection())


@app.route("/api/preview-feed")
def api_preview():
    try:
        posts = fetch_posts(limit=5)
        return jsonify({"ok": True, "posts": posts})
    except Exception as e:
        log.exception("preview-feed failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.errorhandler(500)
def handle_500(e):
    log.exception("Unhandled server error")
    return jsonify({"ok": False, "error": "Internal server error"}), 500


if __name__ == "__main__":
    # debug=True is fine locally, but use_debugger/reloader double-starts —
    # harmless now since workers no longer start from the web process.
    app.run(debug=True, port=5000)