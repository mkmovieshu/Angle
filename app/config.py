# app/config.py
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

# Your Render domain (no https://)
DOMAIN = os.getenv("DOMAIN")  # example: angle-jldx.onrender.com

# ShortXLinks API Key (optional)
SHORTX_API_KEY = os.getenv("SHORTX_API_KEY")

# BIN channel (optional). If not provided, set to None.
_bin_channel = os.getenv("BIN_CHANNEL")
try:
    BIN_CHANNEL = int(_bin_channel) if _bin_channel is not None else None
except ValueError:
    raise RuntimeError(f"Invalid BIN_CHANNEL value: {_bin_channel!r}. It must be an integer chat id.")

# ADMIN chat id for error/alert notifications (optional)
_admin_chat = os.getenv("ADMIN_CHAT_ID")
try:
    ADMIN_CHAT_ID = int(_admin_chat) if _admin_chat is not None else None
except ValueError:
    raise RuntimeError(f"Invalid ADMIN_CHAT_ID value: {_admin_chat!r}. It must be an integer chat id.")

# Basic validation for truly required vars:
_missing = []
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not MONGO_URL:
    _missing.append("MONGO_URL")
if not DOMAIN:
    _missing.append("DOMAIN")

if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")
