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

# Auto-start all three background workers on boot, so a Render restart or
# free-tier sleep/wake cycle doesn't require manually re-clicking Start on
# the dashboard for the app to actually be functional again.
scheduler.start()
telegram_bot.start()
random_poster.start()


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
    app.run(debug=True, port=5000)