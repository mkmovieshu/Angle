import os

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Database
MONGO_URL = os.getenv("MONGO_URL")  # UPDATED
if not MONGO_URL:
    raise RuntimeError("MONGO_URL missing in environment!")

FREE_LIMIT = int(os.getenv("FREE_LIMIT", 5))

# Domain
DOMAIN = os.getenv("DOMAIN", "")

# BIN Channel
BIN_CHANNEL = os.getenv("BIN_CHANNEL")
try:
    BIN_CHANNEL = int(BIN_CHANNEL)
except:
    pass

# API for Pyrogram (optional)
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
