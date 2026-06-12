import threading
import time

from config import POST_INTERVAL
from content_fetcher import fetch_posts
from content_processor import format_post
from poster import post_to_channel
from database import is_already_posted, mark_posted, log_post, set_setting

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _handle_results(post: dict, results: list[dict]):
    """Process per-channel results, mark posted if any succeeded, log each."""
    any_success = False
    errors = []

    for r in results:
        chat_id = r["channel"]
        res = r["result"]
        if res.get("ok"):
            any_success = True
        else:
            errors.append(f"{chat_id}: {res.get('description', 'Unknown error')}")

    if any_success:
        mark_posted(post["link"], post["title"])
        log_post(post["title"], post["link"], "success")
        for err in errors:
            log_post(post["title"], post["link"], "error", err)
    else:
        log_post(post["title"], post["link"], "error", "; ".join(errors) or "Unknown error")

    return any_success


def _run_loop():
    set_setting("running", "1")
    while not _stop_event.is_set():
        try:
            posts = fetch_posts()
            for post in posts:
                if _stop_event.is_set():
                    break
                if is_already_posted(post["link"]):
                    continue

                message = format_post(post)
                results = post_to_channel(message, post)
                _handle_results(post, results)

                # small gap between each post
                _stop_event.wait(10)

        except Exception as exc:
            log_post("SCHEDULER ERROR", "", "error", str(exc))

        # wait for next cycle (interruptible)
        _stop_event.wait(POST_INTERVAL)

    set_setting("running", "0")


def start():
    global _thread, _stop_event
    if _thread and _thread.is_alive():
        return False  # already running
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_run_loop, daemon=True, name="bot-scheduler")
    _thread.start()
    return True


def stop():
    global _thread
    _stop_event.set()
    if _thread:
        _thread.join(timeout=5)
    set_setting("running", "0")
    return True


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def post_now() -> dict:
    """Manually trigger one cycle (runs in background thread)."""
    def _once():
        try:
            posts = fetch_posts()
            results_out = []
            for post in posts:
                if is_already_posted(post["link"]):
                    continue
                message = format_post(post)
                results = post_to_channel(message, post)
                success = _handle_results(post, results)
                results_out.append({
                    "title": post["title"],
                    "status": "ok" if success else "error",
                })
                time.sleep(10)
        except Exception as e:
            log_post("MANUAL POST ERROR", "", "error", str(e))

    t = threading.Thread(target=_once, daemon=True)
    t.start()
    return {"started": True}