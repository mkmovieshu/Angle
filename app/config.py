# app/config.py
"""
Central config for Angle.
Keep the exact env names required by the project.
"""

import os

# --- Required core ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

# NOTE: user insisted on MONGO_URL (not MONGO_URI)
MONGO_URL = os.getenv("MONGO_URL", "")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# --- App behavior ---
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# --- Shortlink / ad behavior flags (added to satisfy handlers & control mode) ---
# If you want to always use direct domain (no shortener), set to "true"
SHORTLINK_PREFER_NO_SHORTENING = os.getenv("SHORTLINK_PREFER_NO_SHORTENING", "true").lower() in ("1", "true", "yes")

# If you prefer to create short links (legacy behavior), set to "true".
# Handlers may check SHORTLINK_PREFER_SHORT first, then SHORTLINK_PREFER_NO_SHORTENING.
SHORTLINK_PREFER_SHORT = os.getenv("SHORTLINK_PREFER_SHORT", "false").lower() in ("1", "true", "yes")

# Shortlink provider defaults (kept for compatibility)
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "https://shortxlinks.com/api")
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")

# --- Domain used for direct ad-return links (no trailing slash) ---
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com").rstrip("/")

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
