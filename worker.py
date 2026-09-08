"""Run this as a separate Render Background Worker (or `python worker.py`)."""
import os

os.environ["RUN_WORKERS"] = "1"

import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

import database as db
import scheduler
import telegram_bot
import random_poster

db.init_db()

for name, start_fn in (
    ("scheduler", scheduler.start),
    ("telegram_bot", telegram_bot.start),
    ("random_poster", random_poster.start),
):
    try:
        start_fn()
    except Exception:
        log.exception("Failed to start %s", name)

log.info("All workers started — keeping process alive")
import time
while True:
    time.sleep(3600)  # keep the container alive; workers run in their own threads