"""
telegram_bot.py — Conversational + engagement layer for the Telegram bot.

Runs alongside your existing Flask app and content-posting scheduler.
Handles:
  - Conversation: FAQ keyword match first (cheap, instant), AI fallback
    (Claude) for anything else, with short per-user history for context.
  - Auto-welcome: greets new members when they join a group.
  - A simple start/stop lifecycle mirroring scheduler.py, so it can be
    controlled from the same dashboard.

Requires: pip install python-telegram-bot==21.* anthropic
"""

import logging
import threading
import asyncio
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, GEMINI_API_KEY, CHANNEL_USERNAMES
import database as db

logger = logging.getLogger(__name__)

# ─── Simple FAQ table — checked before falling back to AI ────────────────────
# Keep this short and specific; a keyword match on a long FAQ will
# misfire on ordinary conversation. Move anything ambiguous to the AI path.
FAQ = {
    "rules": "Here are the group rules: be respectful, no spam, stay on topic.",
    "schedule": "New posts go out daily — check /api/stats for the latest run.",
}

WELCOME_TEMPLATE = (
    "👋 Welcome, {name}! Glad to have you here.\n"
    "Check the pinned message for group rules, and feel free to jump into the conversation."
)

SYSTEM_PROMPT = (
    "You are a friendly, concise assistant for a Telegram group. "
    "Keep replies short (2-3 sentences max) and natural, like a helpful group member — "
    "not a customer support bot."
)


# ─── Conversation handling ────────────────────────────────────────────────────

async def get_ai_reply(user_message: str, history: list[dict]) -> str:
    """Call Gemini (free tier) for a conversational reply, using recent history for context."""
    import time
    from google import genai
    from google.genai import types
    from google.genai import errors

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Gemini's chat format uses role "model" instead of "assistant".
    gemini_history = [
        types.Content(
            role="model" if h["role"] == "assistant" else "user",
            parts=[types.Part.from_text(text=h["content"])],
        )
        for h in history
    ]

    def _call():
        chat = client.chats.create(
            # "-latest" tracks Google's current free-tier Flash model, so this
            # doesn't hard-break every time they retire a dated model name
            # (which is what happened with gemini-2.0-flash).
            model="gemini-flash-latest",
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            history=gemini_history,
        )
        last_exc = None
        for attempt in range(3):
            try:
                response = chat.send_message(user_message)
                return response.text
            except errors.ServerError as e:
                # 503 "high demand" on the free tier is usually transient —
                # worth a couple of short retries before giving up.
                last_exc = e
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
        raise last_exc

    # The SDK call is blocking (sync HTTP under the hood) — run it off the
    # event loop thread so it doesn't stall other bot updates while waiting.
    return await asyncio.to_thread(_call)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user

    # 1. FAQ first — no API call, instant
    lowered = text.lower()
    for keyword, answer in FAQ.items():
        if keyword in lowered:
            await update.message.reply_text(answer)
            db.log_conversation(chat_id, user.id, text, answer, source="faq")
            return

    # 2. Fall back to AI, with recent history for context
    history = db.get_conversation_history(chat_id, user.id, limit=6)
    try:
        reply = await get_ai_reply(text, history)
    except Exception as e:
        logger.exception("AI reply failed")
        reply = "Sorry, I'm having trouble responding right now — try again in a bit."
    await update.message.reply_text(reply)
    db.log_conversation(chat_id, user.id, text, reply, source="ai")


SEARCH_API_URL = "https://9janetmovies.com.ng/api/search"


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "Usage: /search <movie or series name>\nExample: /search toy story"
        )
        return

    def _call():
        resp = requests.get(SEARCH_API_URL, params={"q": query}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    try:
        results = await asyncio.to_thread(_call)
    except requests.RequestException:
        logger.exception("Search API request failed")
        await update.message.reply_text("Couldn't reach the search right now — try again in a bit.")
        return

    if not results:
        await update.message.reply_text(f'No results found for "{query}".')
        return

    top = results[:5]
    lines = [f'🔍 Results for "{query}":']
    buttons = []
    for r in top:
        title = r.get("title", "Untitled")
        year = r.get("year")
        kind = r.get("type", "movie")
        icon = "🎬" if kind == "movie" else "📺"
        slug = r.get("slug", "")
        year_str = f" ({year})" if year else ""
        lines.append(f"{icon} {title}{year_str}")

        if slug:
            link = f"https://9janetmovies.com.ng/{kind}/{slug}"
            buttons.append([InlineKeyboardButton(f"▶️ {title[:30]}", url=link)])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    text = "\n".join(lines)
    poster = top[0].get("poster_url")

    if poster:
        await update.message.reply_photo(photo=poster, caption=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(f"➕ Join {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in CHANNEL_USERNAMES
    ]
    await update.message.reply_text(
        "📢 Never miss a new movie or series — join our channel:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm live in this group — ask me anything, try /search <title> to find a "
        "movie or series, or /invite to grab our channel link."
    )


# ─── Auto-welcome ──────────────────────────────────────────────────────────────

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(f"➕ Join {ch}", url=f"https://t.me/{ch.lstrip('@')}")]
        for ch in CHANNEL_USERNAMES
    ]
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        name = member.first_name or member.username or "there"
        await update.message.reply_text(
            WELCOME_TEMPLATE.format(name=name),
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        db.log_member_join(update.effective_chat.id, member.id, name)


# ─── Bot lifecycle (background thread, same pattern as scheduler.py) ─────────

_app: Application | None = None
_thread: threading.Thread | None = None


def _run():
    global _app
    _app = ApplicationBuilder().token(BOT_TOKEN).build()
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("search", cmd_search))
    _app.add_handler(CommandHandler("invite", cmd_invite))
    _app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # stop_signals=None: signal handlers only work on the main thread,
    # and this runs on a background thread.
    _app.run_polling(stop_signals=None, close_loop=False)


def start() -> bool:
    global _thread
    if _thread and _thread.is_alive():
        return False
    _thread = threading.Thread(target=_run, daemon=True)
    _thread.start()
    return True


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def stop():
    global _app
    if _app is not None:
        _app.stop_running()