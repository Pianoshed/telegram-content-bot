from config import CHANNEL_USERNAME


def format_post(post: dict) -> str:
    title = post["title"]
    content = post["content"]
    link = post["link"]
    tags = post.get("tags", [])

    tag_line = ""
    if tags:
        tag_line = "  ".join(f"#{t.replace(' ', '_')}" for t in tags[:4]) + "\n\n"

    return (
        f"🎬 *{title}*\n\n"
        f"{content}\n\n"
        f"{tag_line}"
        f"👉 [Watch / Read More]({link})\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔔 Stay updated — join {CHANNEL_USERNAME}"
    )


def build_inline_keyboard(post: dict) -> list:
    """Returns a Telegram InlineKeyboardMarkup-compatible structure."""
    return [
        [
            {"text": "▶️ Watch Now", "url": post["link"]},
            {"text": "📢 Share", "url": f"https://t.me/share/url?url={post['link']}&text={post['title']}"},
        ],
        [
            {"text": f"➕ Join {CHANNEL_USERNAME}", "url": f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"},
        ],
    ]