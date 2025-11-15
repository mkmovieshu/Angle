import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

# Your Render domain (no https://)
DOMAIN = os.getenv("DOMAIN")  # example: angle-jldx.onrender.com

# ShortXLinks API Key
SHORTX_API_KEY = os.getenv("SHORTX_API_KEY")

BIN_CHANNEL = int(os.getenv("BIN_CHANNEL"))  # వీడియోలు స్టోర్ ఉన్న channel ID

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")
