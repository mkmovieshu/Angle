# app/telegram/bot.py
from telegram import Bot
from ..config import BOT_TOKEN

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

bot = Bot(token=BOT_TOKEN)
