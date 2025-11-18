# app/config.py
import os

# Core bot
BOT_TOKEN = os.getenv("BOT_TOKEN")  # required

# Note: user requested MONGO_URL naming — keep it exactly
MONGO_URL = os.getenv("MONGO_URL")  # required
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# Limits & behaviour
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))
REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

# Shortlink (shortxlinks.com) integration
# Put your shortxlinks API key in SHORTLINK_API_KEY environment variable
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY")  # optional, but set it
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "https://shortxlinks.com/api")  # default

# Where ad redirects should return to (your service)
# e.g. https://angle-jldx.onrender.com
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com")

# Ad provider fallback URL (used if shortener missing)
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
