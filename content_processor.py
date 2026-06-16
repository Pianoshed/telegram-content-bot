import html
from urllib.parse import quote
from config import CHANNEL_USERNAMES

PRIMARY_CHANNEL = CHANNEL_USERNAMES[0]


def format_post(post: dict) -> str:
    title = html.escape(post["title"])
    content = html.escape(post["content"])
    link = post["link"]
    tags = post.get("tags", [])

    tag_line = ""
    if tags:
        tag_line = "  ".join(f"#{t.replace(' ', '_')}" for t in tags[:4]) + "\n\n"

    watch_line = ""
    if link:
        watch_line = f'👉 <a href="{html.escape(link)}">Watch / Read More</a>\n\n'

    return (
        f"🎬 <b>{title}</b>\n\n"
        f"{content}\n\n"
        f"{tag_line}"
        f"{watch_line}"
        f"━━━━━━━━━━━━━━\n"
        f"🔔 Stay updated — join {PRIMARY_CHANNEL}"
    )


def build_inline_keyboard(post: dict) -> list:
    """Returns a Telegram InlineKeyboardMarkup-compatible structure."""
    link = post.get("link") or ""
    rows = []

    if link.startswith("http://") or link.startswith("https://"):
        rows.append([
            {"text": "▶️ Watch Now", "url": link},
            {"text": "📢 Share", "url": f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(post['title'], safe='')}"},
        ])

    rows.append([
        {"text": f"➕ Join {PRIMARY_CHANNEL}", "url": f"https://t.me/{PRIMARY_CHANNEL.lstrip('@')}"},
    ])
    return rows