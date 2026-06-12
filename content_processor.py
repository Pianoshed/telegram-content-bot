from config import CHANNEL_USERNAMES

PRIMARY_CHANNEL = CHANNEL_USERNAMES[0]


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
        f"🔔 Stay updated — join {PRIMARY_CHANNEL}"
    )


def build_inline_keyboard(post: dict) -> list:
    """Returns a Telegram InlineKeyboardMarkup-compatible structure."""
    return [
        [
            {"text": "▶️ Watch Now", "url": post["link"]},
            {"text": "📢 Share", "url": f"https://t.me/share/url?url={post['link']}&text={post['title']}"},
        ],
        [
            {"text": f"➕ Join {PRIMARY_CHANNEL}", "url": f"https://t.me/{PRIMARY_CHANNEL.lstrip('@')}"},
        ],
    ]