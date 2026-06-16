import re
import requests
from config import BOT_TOKEN, CHANNEL_USERNAMES
from content_processor import build_inline_keyboard


BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _keyboard_payload(post: dict) -> dict:
    buttons = build_inline_keyboard(post)
    return {
        "inline_keyboard": buttons
    }


def _safe_truncate_html(text: str, limit: int = 1024) -> str:
    """Truncate without cutting mid-tag, and close any tags left dangling."""
    if len(text) <= limit:
        return text

    truncated = text[:limit]
    last_lt = truncated.rfind("<")
    last_gt = truncated.rfind(">")
    if last_lt > last_gt:
        truncated = truncated[:last_lt]

    for tag in ("a", "b"):
        opens = len(re.findall(f"<{tag}[ >]", truncated))
        closes = truncated.count(f"</{tag}>")
        if opens > closes:
            truncated += f"</{tag}>"

    return truncated


def post_to_channel(text: str, post: dict) -> list[dict]:
    """Send a message (with photo if available, else text) to all configured channels."""
    image_url = post.get("image")
    reply_markup = _keyboard_payload(post)
    results = []

    for chat_id in CHANNEL_USERNAMES:
        if image_url:
            result = _send_photo(chat_id, image_url, text, reply_markup)
        else:
            result = _send_message(chat_id, text, reply_markup)
        results.append({"channel": chat_id, "result": result})

    return results


def _send_message(chat_id: str, text: str, reply_markup: dict) -> dict:
    resp = requests.post(
        f"{BASE}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "reply_markup": reply_markup,
        },
        timeout=15,
    )
    return resp.json()


def _send_photo(chat_id: str, photo_url: str, caption: str, reply_markup: dict) -> dict:
    resp = requests.post(
        f"{BASE}/sendPhoto",
        json={
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": _safe_truncate_html(caption, 1024),
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        },
        timeout=15,
    )
    return resp.json()


def test_connection() -> dict:
    """Verify bot token is valid."""
    resp = requests.get(f"{BASE}/getMe", timeout=10)
    return resp.json()