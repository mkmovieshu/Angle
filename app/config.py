# app/config.py
import os

# REQUIRED envs
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
DOMAIN = os.getenv("DOMAIN")  # e.g. angle-jldx.onrender.com

# Optional / helper envs
SHORTX_API_KEY = os.getenv("SHORTX_API_KEY")

# BIN channel (where videos are posted) - numeric chat id or None
_bin_channel = os.getenv("BIN_CHANNEL")
try:
    BIN_CHANNEL = int(_bin_channel) if _bin_channel not in (None, "") else None
except ValueError:
    raise RuntimeError(f"Invalid BIN_CHANNEL value: {_bin_channel!r}. Must be integer chat id.")

# ADMIN chat id for notifications - numeric or None
_admin = os.getenv("ADMIN_CHAT_ID")
try:
    ADMIN_CHAT_ID = int(_admin) if _admin not in (None, "") else None
except ValueError:
    raise RuntimeError(f"Invalid ADMIN_CHAT_ID value: {_admin!r}. Must be integer chat id.")

# REQUIRED GROUP enforcement (optional)
_required = os.getenv("REQUIRED_GROUP_ID")
try:
    REQUIRED_GROUP_ID = int(_required) if _required not in (None, "") else None
except ValueError:
    raise RuntimeError(f"Invalid REQUIRED_GROUP_ID value: {_required!r}. Must be integer chat id (e.g. -100123...)")

# Invite link or public username to show in Join prompt
# handlers expect REQUIRED_GROUP_LINK — keep both names for compatibility
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK") or os.getenv("REQUIRED_GROUP_INVITE") or os.getenv("REQUIRED_GROUP_URL")
REQUIRED_GROUP_USERNAME = os.getenv("REQUIRED_GROUP_USERNAME")  # optional t.me/<username>

# Free limit: default 5
_free_limit = os.getenv("FREE_LIMIT")
try:
    FREE_LIMIT = int(_free_limit) if _free_limit not in (None, "") else 5
except ValueError:
    FREE_LIMIT = 5

# Basic validation for truly required envs
_missing = []
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not MONGO_URL:
    _missing.append("MONGO_URL")
if not DOMAIN:
    _missing.append("DOMAIN")

if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")
