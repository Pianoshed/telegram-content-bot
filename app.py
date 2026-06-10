from flask import Flask, render_template, jsonify, request
from config import SECRET_KEY
import database as db
import scheduler
from poster import test_connection
from content_fetcher import fetch_posts

app = Flask(__name__)
app.secret_key = SECRET_KEY

db.init_db()


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── API ─────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    stats = db.get_stats()
    stats["scheduler_running"] = scheduler.is_running()
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