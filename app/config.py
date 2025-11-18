# app/config.py
"""
Central config for Angle — simplified & commented.
Keep required env names exactly as-is (BOT_TOKEN, MONGO_URL, MONGO_DB_NAME).
Only shortlink-related vars typically need editing for your use-case.
"""

import os
import json

# -------------------------
# REQUIRED CORE (DO NOT RENAME)
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

# NOTE: you insisted on MONGO_URL (not MONGO_URI) — keep this exact name
MONGO_URL = os.getenv("MONGO_URL", "")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")

# -------------------------
# APP BEHAVIOR (can leave defaults)
# -------------------------
# How many free videos per user before showing ad flow
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

# Link used in menus to encourage joining your group
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

# Fallback/provider url used in ad session records (optional)
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Domain of your deployed app — used to build ad return URL.
# Example: "https://angle-jldx.onrender.com"
DOMAIN = os.getenv("DOMAIN", "https://angle-jldx.onrender.com").rstrip("/")

# -------------------------
# SHORTLINK / AD RETURN CONFIG
# Only these are the ones you normally need to edit.
# -------------------------

# If you want NO shortener and prefer direct ad return URL, set to "true".
# e.g. export SHORTLINK_PREFER_NO_SHORTENING=true
SHORTLINK_PREFER_NO_SHORTENING = os.getenv("SHORTLINK_PREFER_NO_SHORTENING", "false").lower() in ("1", "true", "yes")

# If True, attempt to create shortlinks via SHORTLINK_CREATE_TEMPLATE + SHORTLINK_API_KEY
SHORTLINK_PREFER_SHORT = os.getenv("SHORTLINK_PREFER_SHORT", "true").lower() in ("1", "true", "yes")

# TEMPLATE: change this to match the shortener provider you will use.
# Must include placeholders that the code understands: {key}, {return_url}
# Additional placeholders available: {token}, {uid}, {encoded_return}
#
# Examples:
# - shortxlinks (GET JSON): "https://shortxlinks.com/api?api={key}&url={return_url}"
# - tnshort (GET JSON): "https://tnshort.net/api?api={key}&url={return_url}"
# - custom POST endpoint: put the POST URL here and set SHORTLINK_METHOD=post
#
# Default below uses shortxlinks example (you can change this to any provider).
SHORTLINK_CREATE_TEMPLATE = os.getenv(
    "SHORTLINK_CREATE_TEMPLATE",
    "https://shortxlinks.com/api?api={key}&url={return_url}"
)

# The API key/token for your shortener provider (if required)
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")

# HTTP method to use when creating shortlink. Allowed: "get" or "post"
# If provider needs POST JSON, set to "post".
SHORTLINK_METHOD = os.getenv("SHORTLINK_METHOD", "get").lower()

# Optional additional headers for shortlink provider API (JSON string)
# e.g. export SHORTLINK_REQUEST_HEADERS='{"Authorization":"Bearer ..."}'
SHORTLINK_REQUEST_HEADERS = os.getenv("SHORTLINK_REQUEST_HEADERS", "")

# -------------------------
# LOGGING / EXTRA (safe defaults)
# -------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
