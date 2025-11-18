# app/config.py
"""
Central configuration for Angle project.

Keep these exact environment variable NAMES (do not rename) as requested:
BOT_TOKEN, MONGO_URL, MONGO_DB_NAME, FREE_LIMIT, REQUIRED_GROUP_LINK,
AD_PROVIDER_URL, SHORTLINK_API_URL, SHORTLINK_API_KEY, DOMAIN, LOG_LEVEL

Also optional shortlink preferences:
SHORTLINK_PREFER_NO_SHORTENING (if "1" or "true" then no shortening)
"""
from os import getenv
import logging

LOG_LEVEL = getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

BOT_TOKEN = getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

# *** IMPORTANT: user insisted on MONGO_URL (not MONGO_URI) ***
MONGO_URL = getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

MONGO_DB_NAME = getenv("MONGO_DB_NAME", "video_bot_db")

FREE_LIMIT = int(getenv("FREE_LIMIT", "5"))

REQUIRED_GROUP_LINK = getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")
REQUIRED_GROUP_ID = getenv("REQUIRED_GROUP_ID")  # optional numeric id

AD_PROVIDER_URL = getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Shortlink provider (configurable)
# Example: https://shortxlinks.com (but prefer full API endpoint if available)
SHORTLINK_API_URL = getenv("SHORTLINK_API_URL", "https://shortxlinks.com/api")
SHORTLINK_API_KEY = getenv("SHORTLINK_API_KEY", "")

# If set to "1" or "true" (case-ins) prefer returning a direct URL (no shortening)
SHORTLINK_PREFER_NO_SHORTENING = getenv("SHORTLINK_PREFER_NO_SHORTENING", "0").lower() in ("1", "true", "yes")

# Domain used for ad returns (your app domain)
DOMAIN = getenv("DOMAIN", "https://angle-jldx.onrender.com")

# Logging
def get_logger(name: str):
    return logging.getLogger(name)
