# app/config.py
import os

# Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

# Mongo (you insisted on MONGO_URL name)
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

# DB name
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# Free videos per user
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

# Required join group link (fallback)
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

# Domain for ad return callbacks (must include protocol, e.g. https://angle-jldx.onrender.com)
DOMAIN = os.getenv("DOMAIN")
if not DOMAIN:
    # Not fatal — but recommended to set for ad callbacks / shortlinks
    DOMAIN = os.getenv("PUBLIC_URL", "https://angle-jldx.onrender.com")

# Shortlink provider API key (shortxlinks.com API token)
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY")  # optional

# Shortlink API base (allow override)
SHORTLINK_API_BASE = os.getenv("SHORTLINK_API_BASE", "https://shortxlinks.com/api")

# Admin user ids (comma separated)
ADMIN_USERS = [int(x) for x in os.getenv("ADMIN_USERS", "").split(",") if x.strip()]  # e.g. "12345678,87654321"

# Other optional settings
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)
