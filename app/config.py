# app/config.py
import os

# ----- Required (do not rename these) -----
BOT_TOKEN = os.getenv("BOT_TOKEN")  # required
MONGO_URL = os.getenv("MONGO_URL")  # required (you insisted URL, not URI)
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# ----- App defaults -----
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")
REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional numeric

# ----- Shortlink / ad provider settings -----
# Shortlink provider base API endpoint (ShortXLinks uses /api)
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "https://shortxlinks.com/api")
# API key (you provided: 102b88bf284c1535f6d74adaab1fc7d07d842cf8)
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "102b88bf284c1535f6d74adaab1fc7d07d842cf8")
# If True, prefer returning the short link; if shortener fails, fall back to the plain return URL.
SHORTLINK_PREFER_SHORT = os.getenv("SHORTLINK_PREFER_SHORT", "true").lower() in ("1","true","yes")

# Public domain of your app, used to build ad return URLs
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com")

# Ad provider (fallback) — keep configurable
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
