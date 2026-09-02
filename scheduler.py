import threading
import time

from config import DAILY_POST_CAP, REPOST_COOLDOWN_DAYS
from content_fetcher import fetch_posts
from content_processor import format_post
from poster import post_to_channel
from database import (
    is_already_posted,
    mark_posted,
    log_post,
    set_setting,
    get_daily_post_count,
    increment_daily_post_count,
    get_repost_candidate,
    mark_reposted,
)

_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Spread the daily cap evenly across 24h instead of bursting.
# e.g. DAILY_POST_CAP=50 -> a post roughly every 28.8 minutes.
POST_SPACING_SECONDS = 86400 / DAILY_POST_CAP


def _handle_results(post: dict, results: list[dict], is_repost: bool = False):
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
        if is_repost:
            mark_reposted(post["link"])
            log_post(post["title"], post["link"], "success", "repost")
        else:
            mark_posted(post["link"], post["title"], post)
            log_post(post["title"], post["link"], "success")
        increment_daily_post_count()
        for err in errors:
            log_post(post["title"], post["link"], "error", err)
    else:
        log_post(post["title"], post["link"], "error", "; ".join(errors) or "Unknown error")

    return any_success


def _next_item():
    """Pick the next thing to post: prefer fresh content, fall back to a
    repost of older queued content so the channel doesn't go quiet."""
    posts = fetch_posts()
    for post in posts:
        if not is_already_posted(post["link"]):
            return post, False  # (post, is_repost)

    candidate = get_repost_candidate(REPOST_COOLDOWN_DAYS)
    if candidate:
        return candidate, True

    return None, False


def _run_loop():
    set_setting("running", "1")
    while not _stop_event.is_set():
        try:
            if get_daily_post_count() >= DAILY_POST_CAP:
                # Cap hit for today — recheck hourly; resets automatically
                # at midnight via get_daily_post_count().
                _stop_event.wait(3600)
                continue

            post, is_repost = _next_item()
            if post:
                message = format_post(post)
                results = post_to_channel(message, post)
                _handle_results(post, results, is_repost=is_repost)
            else:
                log_post(
                    "SCHEDULER", "", "error",
                    "Nothing to post: no new content and no repost candidates available",
                )

        except Exception as exc:
            log_post("SCHEDULER ERROR", "", "error", str(exc))

        _stop_event.wait(POST_SPACING_SECONDS)

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
    """Manually trigger one post right now — bypasses the daily cap and
    spacing, but still prefers fresh content over a repost."""
    def _once():
        try:
            post, is_repost = _next_item()
            if not post:
                log_post("MANUAL POST", "", "error", "Nothing available to post")
                return
            message = format_post(post)
            results = post_to_channel(message, post)
            _handle_results(post, results, is_repost=is_repost)
        except Exception as e:
            log_post("MANUAL POST ERROR", "", "error", str(e))

    t = threading.Thread(target=_once, daemon=True)
    t.start()
    return {"started": True}