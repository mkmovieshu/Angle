# telegram/bot.py
import asyncio
import os
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

from telegram.handlers import start_handler, next_handler
from telegram.handlers_ad import handle_ad_check

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(next_handler, pattern="^next"))
    app.add_handler(CallbackQueryHandler(handle_ad_check, pattern="^ad_check"))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
