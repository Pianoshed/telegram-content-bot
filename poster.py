import requests
from config import BOT_TOKEN, CHANNEL_USERNAME
from content_processor import build_inline_keyboard


BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _keyboard_payload(post: dict) -> dict:
    buttons = build_inline_keyboard(post)
    return {
        "inline_keyboard": buttons
    }


def post_to_channel(text: str, post: dict) -> dict:
    """Send a message (with photo if available, else text) to the channel."""
    image_url = post.get("image")
    reply_markup = _keyboard_payload(post)

    if image_url:
        return _send_photo(image_url, text, reply_markup)
    return _send_message(text, reply_markup)


def _send_message(text: str, reply_markup: dict) -> dict:
    resp = requests.post(
        f"{BASE}/sendMessage",
        json={
            "chat_id": CHANNEL_USERNAME,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
            "reply_markup": reply_markup,
        },
        timeout=15,
    )
    return resp.json()


def _send_photo(photo_url: str, caption: str, reply_markup: dict) -> dict:
    resp = requests.post(
        f"{BASE}/sendPhoto",
        json={
            "chat_id": CHANNEL_USERNAME,
            "photo": photo_url,
            "caption": caption[:1024],  # Telegram caption limit
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        },
        timeout=15,
    )
    return resp.json()


def test_connection() -> dict:
    """Verify bot token is valid."""
    resp = requests.get(f"{BASE}/getMe", timeout=10)
    return resp.json()