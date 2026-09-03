"""
random_poster.py — Posts a random "spotlight" movie to your channels at
unpredictable intervals, independent of scheduler.py's regular RSS-based
posting. Controlled separately (its own start/stop), so you can run it
alongside or instead of the scheduler.
"""

import threading
import random
import requests

from config import RANDOM_POST_MIN_HOURS, RANDOM_POST_MAX_HOURS
from poster import post_to_channel
from content_processor import format_post
from database import log_post

RANDOM_MOVIE_API_URL = "https://9janetmovies.com.ng/api/movies/random"

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _fetch_random_movie() -> dict:
    resp = requests.get(RANDOM_MOVIE_API_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _to_post(movie: dict) -> dict:
    """Adapt a Movie.to_dict() response into the shape post_to_channel /
    format_post expect (same shape fetch_posts() produces)."""
    slug = movie.get("slug", "")
    return {
        "title": movie.get("title", "Untitled"),
        "content": movie.get("description") or "🎲 Today's random pick — check it out!",
        "link": f"https://9janetmovies.com.ng/movie/{slug}" if slug else "https://9janetmovies.com.ng",
        "image": movie.get("poster_url"),
        "tags": [movie.get("genre")] if movie.get("genre") else [],
    }


def _post_once():
    movie = _fetch_random_movie()
    post = _to_post(movie)
    message = "🎲 <b>Random Pick!</b>\n\n" + format_post(post)
    results = post_to_channel(message, post)

    any_success = any(r["result"].get("ok") for r in results)
    if any_success:
        log_post(post["title"], post["link"], "success", "random spotlight")
    else:
        errors = "; ".join(
            f'{r["channel"]}: {r["result"].get("description", "Unknown error")}'
            for r in results
        )
        log_post(post["title"], post["link"], "error", errors or "random spotlight failed on all channels")


def _run_loop():
    while not _stop_event.is_set():
        wait_seconds = random.uniform(RANDOM_POST_MIN_HOURS, RANDOM_POST_MAX_HOURS) * 3600
        # wait() returns True if stop_event was set during the wait (i.e. we
        # were told to stop, not that the timer finished) — bail out cleanly.
        if _stop_event.wait(wait_seconds):
            break

        try:
            _post_once()
        except Exception as exc:
            log_post("RANDOM POST ERROR", "", "error", str(exc))


def start() -> bool:
    global _thread, _stop_event
    if _thread and _thread.is_alive():
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_run_loop, daemon=True, name="random-poster")
    _thread.start()
    return True


def stop() -> bool:
    global _thread
    _stop_event.set()
    if _thread:
        _thread.join(timeout=5)
    return True


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()