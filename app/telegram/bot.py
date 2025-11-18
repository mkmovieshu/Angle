# main.py — Full working Telegram bot with ShortXLinks integration
# Author: ChatGPT (Replace-ready)
# Works on Render/Heroku/PythonAnywhere/Local

import os
import requests
import telebot
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Load .env values
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHORTX_API_KEY = os.getenv("SHORTX_API_KEY")

if not BOT_TOKEN:
    raise Exception("ERROR: BOT_TOKEN missing in environment variables (.env)")

if not SHORTX_API_KEY:
    raise Exception("ERROR: SHORTX_API_KEY missing in environment variables (.env)")

bot = telebot.TeleBot(BOT_TOKEN)

# ------------------------------------------------------------------------------

def create_short_link(long_url: str) -> str | None:
    """Shorten URL using ShortXLinks (format=text). Returns short URL or None."""
    try:
        encoded_url = quote_plus(long_url, safe=':/?&=#')

        api_url = (
            f"https://shortxlinks.com/api?"
            f"api={SHORTX_API_KEY}&url={encoded_url}&format=text"
        )

        resp = requests.get(api_url, timeout=10)
        short = resp.text.strip()

        # API returns "" when failed → treat as failure
        if short == "":
            return None

        return short

    except Exception as e:
        print("ERROR calling ShortXLinks:", e)
        return None

# ------------------------------------------------------------------------------

@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "Send me any full URL (starting with http/https) — I will return a short link."
    )

# ------------------------------------------------------------------------------

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(message):
    text = message.text.strip()

    # Basic URL check
    if not (text.startswith("http://") or text.startswith("https://")):
        bot.reply_to(message, "Send a proper full link like:\nhttps://example.com/page")
        return

    bot.send_chat_action(message.chat.id, "typing")

    short = create_short_link(text)

    if not short:
        bot.reply_to(message, "Shortlink generate కాలేదు. నీ URL లేదా API key చెక్ చేసుకో.")
        return

    bot.reply_to(message, f"Short Link:\n{short}")

# ------------------------------------------------------------------------------

print("Bot running…")
bot.infinity_polling(timeout=20, long_polling_timeout=5)
