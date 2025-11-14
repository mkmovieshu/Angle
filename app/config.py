# app/config.py
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_bot_db")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip()]
BIN_CHANNEL = os.getenv("BIN_CHANNEL", None)
FREE_BATCH = int(os.getenv("FREE_BATCH","5"))
AD_TARGET_URL = os.getenv("AD_TARGET_URL","https://example.com/adpage")
DOMAIN = os.getenv("DOMAIN", None)
ADMIN_CONTACT_URL = os.getenv("ADMIN_CONTACT_URL", "")
SUBSCRIBE_IMAGE_URL = os.getenv("SUBSCRIBE_IMAGE_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
BOT_NAME = os.getenv("BOT_NAME", "ANGEL")

# Premium plans (days -> label & price example)
PREMIUM_PLANS = {
    "plan_10": {"days":10, "label":"10 days - Trial", "price_label":"₹99"},
    "plan_20": {"days":20, "label":"20 days - Standard", "price_label":"₹179"},
    "plan_30": {"days":30, "label":"30 days - Pro", "price_label":"₹249"},
}
