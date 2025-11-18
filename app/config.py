# app/config.py
"""
Central configuration.
Use MONGO_URL (not MONGO_URI). Do NOT rename this variable in your environment.
"""

import os
from typing import Optional

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

# <-- IMPORTANT: use MONGO_URL only. Do NOT use MONGO_URI in env.
MONGO_URL: str = os.getenv("MONGO_URL", "").strip()

# Database name
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "video_bot_db").strip()

# FREE_LIMIT etc.
FREE_LIMIT: int = int(os.getenv("FREE_LIMIT", "5"))

# Force-subscribe group config
REQUIRED_GROUP_ID: Optional[int] = None
_req = os.getenv("REQUIRED_GROUP_ID", "").strip()
if _req:
    try:
        REQUIRED_GROUP_ID = int(_req)
    except Exception:
        REQUIRED_GROUP_ID = None

REQUIRED_GROUP_LINK: str = os.getenv("REQUIRED_GROUP_LINK", "").strip()

# Shortener / Ads
SHORTNER_URL: str = os.getenv("SHORTNER_URL", "").strip()
SHORTNER_API_KEY: str = os.getenv("SHORTNER_API_KEY", "").strip()

# Admin / domain
_admin = os.getenv("ADMIN_CHAT_ID", "").strip()
ADMIN_CHAT_ID: Optional[int] = None
if _admin:
    try:
        ADMIN_CHAT_ID = int(_admin)
    except Exception:
        ADMIN_CHAT_ID = None

DOMAIN: str = os.getenv("DOMAIN", "").strip()

# Toggles
DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
DISABLE_BIN_IMPORTER: bool = os.getenv("DISABLE_BIN_IMPORTER", "false").lower() in ("1", "true", "yes")

# Collection names (centralized)
VIDEO_COLLECTION_NAME: str = os.getenv("VIDEO_COLLECTION_NAME", "videos")
USER_COLLECTION_NAME: str = os.getenv("USER_COLLECTION_NAME", "users")
AD_SESSIONS_COLLECTION_NAME: str = os.getenv("AD_SESSIONS_COLLECTION_NAME", "ad_sessions")

# Safety check: required envs
_missing = []
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not MONGO_URL:
    _missing.append("MONGO_URL")

if _missing and not DEBUG:
    raise RuntimeError("Missing required env vars: " + ", ".join(_missing))


def summary() -> str:
    return (
        f"BOT_TOKEN={'set' if bool(BOT_TOKEN) else 'MISSING'}, "
        f"MONGO_URL={'set' if bool(MONGO_URL) else 'MISSING'}, "
        f"MONGO_DB_NAME={MONGO_DB_NAME}, FREE_LIMIT={FREE_LIMIT}, "
        f"REQUIRED_GROUP_LINK={'set' if bool(REQUIRED_GROUP_LINK) else 'not set'}, "
        f"SHORTNER_URL={'set' if bool(SHORTNER_URL) else 'not set'}, "
        f"DEBUG={DEBUG}"
    )
