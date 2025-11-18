# app/config.py
"""
Central config file for Angle (replace-ready).
Keep the exact environment variable NAMES required by your memory:
BOT_TOKEN, MONGO_URL, MONGO_DB_NAME, FREE_LIMIT, REQUIRED_GROUP_LINK,
AD_PROVIDER_URL, SHORTLINK_API_URL, SHORTLINK_API_KEY, DOMAIN, LOG_LEVEL
"""

import os

# Required keys (will raise errors if missing where appropriate in code)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    # For local dev you can set a dummy token, but in production this must exist
    # We keep same name as requested by you.
    raise RuntimeError("BOT_TOKEN required in env")

# IMPORTANT: user insisted on MONGO_URL (not MONGO_URI)
MONGO_URL = os.getenv("MONGO_URL", "")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# Limit of free videos per new user
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

# Group join requirement / links
REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional numeric id
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

# Ad provider: if you want a special provider base, set it (not used for shortening now)
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Shortlink config (kept for compatibility but NOT used in direct mode)
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "https://shortxlinks.com/api")
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")

# Domain: IMPORTANT — this is the domain used to build the direct ad-return URL.
# Example: https://angle-jldx.onrender.com  OR https://example.com (no trailing slash)
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com").rstrip("/")

# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
