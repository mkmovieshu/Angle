# app/telegram/bot.py
# Async Telegram bot using python-telegram-bot v20+
# Replace-ready file — start point for the whole Telegram subsystem.

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# load env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

# Import handlers after setting logging/env so they can import config safely
from app.telegram import handlers  # noqa: E402 (handlers will register with the app)

def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers defined in app.telegram.handlers (module)
    handlers.register_handlers(app)

    return app

async def run():
    app = build_app()
    logger.info("Starting bot (async)…")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # keep running until cancelled
    await app.updater.idle()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
