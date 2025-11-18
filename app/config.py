import os

# ===========================================
# BASIC BOT SETTINGS
# ===========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL missing")

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")


# ===========================================
# AD / SHORTLINK SETTINGS
# ===========================================
# AD_PROVIDER_URL must be advertiser domain URL
# Example:
#   https://ads.example.com/view?ret={return_url}
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Shortener (optional)
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "")

# MAIN DOMAIN for callback
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com")

# If true → do NOT use shortener → user sees advertiser domain only
SHORTLINK_PREFER_NO_SHORTENING = os.getenv("SHORTLINK_PREFER_NO_SHORTENING", "false").lower() in ("true", "1", "yes")


# ===========================================
# LOGGING
# ===========================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
