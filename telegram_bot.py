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

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, GEMINI_API_KEY
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
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    # Gemini's chat format uses role "model" instead of "assistant", and
    # wraps text in a "parts" list.
    gemini_history = [
        {"role": "model" if h["role"] == "assistant" else "user", "parts": [h["content"]]}
        for h in history
    ]

    def _call():
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT,
        )
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(user_message)
        return response.text

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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey! I'm live in this group — ask me anything.")


# ─── Auto-welcome ──────────────────────────────────────────────────────────────

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        name = member.first_name or member.username or "there"
        await update.message.reply_text(WELCOME_TEMPLATE.format(name=name))
        db.log_member_join(update.effective_chat.id, member.id, name)


# ─── Bot lifecycle (background thread, same pattern as scheduler.py) ─────────

_app: Application | None = None
_thread: threading.Thread | None = None


def _run():
    global _app
    _app = ApplicationBuilder().token(BOT_TOKEN).build()
    _app.add_handler(CommandHandler("start", cmd_start))
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