# app/config.py
import os
from datetime import timedelta, datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

MONGO_URL = os.getenv("MONGO_URL", "")
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))  # channel id where videos are stored
DOMAIN = os.getenv("DOMAIN", "").rstrip("/")  # e.g. https://angle-jldx.onrender.com
SHORTX_API = os.getenv("SHORTX_API", "")  # optional shortener api token

# How many free videos per cycle before asking to watch ad
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

# Admin/contact info for premium purchases
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@your_admin_username")
# For force-subscribe group (optional)
REQUIRED_GROUP_ID = int(os.getenv("REQUIRED_GROUP_ID", "0"))
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "")

# Default premium durations (days)
PREMIUM_PLANS = {
    "10d": 10,
    "20d": 20,
    "30d": 30,
}

# helper
def premium_expires_at(days: int):
    return datetime.utcnow() + timedelta(days=days)
    BIN_CHANNEL = os.getenv("BIN_CHANNEL")
try:
    BIN_CHANNEL = int(BIN_CHANNEL)
except Exception:
    BIN_CHANNEL = BIN_CHANNEL  # keep username string if not integer
