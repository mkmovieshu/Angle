# app/telegram/handlers.py
import os
import logging
import uuid
import time
from typing import Dict, Any, Optional

import httpx
from pymongo import MongoClient
from urllib.parse import urljoin, urlencode

from app.config import (
    BOT_TOKEN,
    MONGO_URL,
    MONGO_DB_NAME,
    FREE_LIMIT,
    REQUIRED_GROUP_LINK,
    AD_PROVIDER_URL,
    SHORTLINK_API_URL,
    SHORTLINK_API_KEY,
    SHORTLINK_PREFER_NO_SHORTENING,
    DOMAIN,
    get_logger,
)

logger = get_logger(__name__)

# Validate critical config (BOT_TOKEN and MONGO_URL already validated by config module)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Mongo client
client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]

# Preserve exact collection names
videos_col = db.get_collection("videos")
users_col = db.get_collection("users")
ad_sessions_col = db.get_collection("ad_sessions")

# ---- Telegram helpers ----
def safe_int_chat_id(chat_id):
    try:
        return int(chat_id)
    except Exception:
        return None

def tg_request(method: str, payload: Dict[str, Any], timeout: float = 10.0):
    """
    Wrapper for Telegram API calls (sync, uses httpx).
    Returns parsed JSON on success or the error JSON if Telegram returned ok==False.
    """
    url = urljoin(TELEGRAM_API, method)
    try:
        logger.debug("TG REQ -> %s payload keys=%s", url, list(payload.keys()))
        r = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        logger.exception("tg_request network error %s %s", url, exc)
        return None

    text = r.text or ""
    logger.info("tg_request response status=%s body=%s", r.status_code, (text[:2000] + ("..." if len(text) > 2000 else "")))

    try:
        j = r.json()
    except Exception:
        logger.error("tg_request: response not JSON status=%s body=%s", r.status_code, text[:1000])
        return None

    if not j.get("ok", False):
        logger.error("Telegram API returned error: %s", j)
        return j
    return j

def send_message(chat_id: int, text: str, reply_markup: Optional[Dict]=None, parse_mode="HTML"):
    if not text or not text.strip():
        logger.error("Refusing to send empty message to %s", chat_id)
        return None
    cid = safe_int_chat_id(chat_id)
    if cid is None:
        logger.error("Invalid chat_id for send_message: %s", chat_id)
        return None
    payload = {"chat_id": cid, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("sendMessage", payload)

def send_video(chat_id: int, file_id: str, caption: str = "", reply_markup: Optional[Dict]=None):
    if not file_id:
        logger.error("No file_id provided to send_video for chat %s", chat_id)
        return None
    cid = safe_int_chat_id(chat_id)
    if cid is None:
        logger.error("Invalid chat_id for send_video: %s", chat_id)
        return None
    payload = {"chat_id": cid, "video": file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("sendVideo", payload)

def answer_callback(callback_id: str, text: Optional[str]=None, show_alert: bool=False):
    payload = {"callback_query_id": callback_id, "show_alert": show_alert}
    if text:
        payload["text"] = text
    return tg_request("answerCallbackQuery", payload)

# ---- UI / menus ----
def build_main_menu():
    keyboard = {
        "inline_keyboard": [
            [{"text": "📺 Videos", "callback_data": "videos:0"}],
            [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}],
        ]
    }
    return keyboard

# ---- DB helpers ----
def ensure_user_doc(user_id: int):
    u = users_col.find_one({"user_id": user_id})
    if not u:
        users_col.insert_one({
            "user_id": user_id,
            "free_remaining": FREE_LIMIT,
            "cursor": 0,
            "joined": False,
        })
        return users_col.find_one({"user_id": user_id})
    return u

def get_next_video_for_user(user_id: int):
    u = ensure_user_doc(user_id)
    cursor = u.get("cursor", 0)
    doc_cursor = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc_cursor)
    if not docs:
        return None
    return docs[0]

def increment_cursor(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"cursor": 1}})

def create_ad_session(user_id: int):
    token = str(uuid.uuid4())
    provider_url = AD_PROVIDER_URL
    doc = {
        "token": token,
        "user_id": user_id,
        "provider_url": provider_url,
        "completed": False,
        "created_at": int(time.time())
    }
    ad_sessions_col.insert_one(doc)
    return doc

# ---- Shortlink integration ----
def _make_shortlink_with_provider(long_url: str) -> Optional[str]:
    """
    Try to create a shortlink via configured SHORTLINK_API_URL and SHORTLINK_API_KEY.
    Provider expected API: POST or GET depending on provider. We'll try POST with common JSON/FORM
    and fallback to GET query.
    Returns shortened URL string or None on failure.
    """
    # If user prefers no shortening, return original
    if SHORTLINK_PREFER_NO_SHORTENING:
        logger.info("SHORTLINK_PREFER_NO_SHORTENING set, returning long_url as-is")
        return long_url

    if not SHORTLINK_API_URL:
        logger.warning("SHORTLINK_API_URL not configured; skipping shortening")
        return None

    headers = {"User-Agent": "AngleShortener/1.0"}
    try:
        # Try POST JSON first
        payload = {"api": SHORTLINK_API_KEY, "url": long_url}
        logger.debug("Attempting shortlink POST to %s payload=%s", SHORTLINK_API_URL, payload)
        r = httpx.post(SHORTLINK_API_URL, json=payload, headers=headers, timeout=8.0)
        if r.status_code == 200:
            try:
                j = r.json()
                # flexible parsing: provider may return {'status':'success','shortenedUrl':...} or {'short':...}
                short_url = None
                if isinstance(j, dict):
                    short_url = j.get("shortenedUrl") or j.get("short") or j.get("short_link") or j.get("url")
                if short_url:
                    logger.info("Shortlink created (POST): %s", short_url)
                    return short_url
            except Exception:
                logger.exception("shortlink provider returned non-json or parse failed (POST). status=%s body=%s", r.status_code, r.text[:500])

        # If POST didn't work, try GET with query params
        logger.debug("Attempting shortlink GET fallback to %s", SHORTLINK_API_URL)
        params = {"api": SHORTLINK_API_KEY, "url": long_url}
        r2 = httpx.get(SHORTLINK_API_URL, params=params, headers=headers, timeout=8.0)
        if r2.status_code == 200:
            try:
                j2 = r2.json()
                if isinstance(j2, dict):
                    short_url = j2.get("shortenedUrl") or j2.get("short") or j2.get("short_link") or j2.get("url")
                    if short_url:
                        logger.info("Shortlink created (GET): %s", short_url)
                        return short_url
            except Exception:
                logger.exception("shortlink provider returned non-json or parse failed (GET). status=%s body=%s", r2.status_code, r2.text[:500])
        logger.warning("Shortlink creation failed: status codes %s / %s", r.status_code if 'r' in locals() else None, r2.status_code if 'r2' in locals() else None)
    except Exception as exc:
        logger.exception("shortlink creation exception: %s", exc)
    return None

def create_ad_open_url(token: str, uid: int) -> str:
    """
    Build the URL the user will open to watch the ad.
    By default we construct a return URL on our domain that ad networks/shortener should redirect back to:
      {SHORTLINK_API_URL or DOMAIN}/ad/return?token={token}&uid={uid}
    Then we try to shorten it (if provider configured).
    """
    # canonical return URL (on our domain)
    return_url = f"{DOMAIN.rstrip('/')}/ad/return?token={token}&uid={uid}"
    # Try provider based shortlink
    shortened = _make_shortlink_with_provider(return_url)
    if shortened:
        return shortened
    # fallback: if provider not available, return a plain (non-shortened) URL or AD_PROVIDER_URL
    # If AD_PROVIDER_URL set to external ad network, prefer it (but must include token/uid)
    if AD_PROVIDER_URL and "{token}" in AD_PROVIDER_URL:
        return AD_PROVIDER_URL.format(token=token, uid=uid)
    if AD_PROVIDER_URL and "?" in AD_PROVIDER_URL:
        # append token/uid as query if placeholders not used
        sep = "&" if "?" in AD_PROVIDER_URL else "?"
        return f"{AD_PROVIDER_URL}{sep}token={token}&uid={uid}"
    # last resort: return the local return_url
    return return_url

# ---- exported function used by routes.py ----
async def handle_update(data: Dict[str, Any]):
    # wrapper to accept webhook update shape (telegram JSON)
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    elif "inline_query" in data:
        logger.info("Inline query ignored")
    else:
        logger.info("Unhandled update type: %s", type(data))

# ---- message handlers ----
async def _handle_message(msg: Dict[str, Any]):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    text = msg.get("text", "")

    logger.info("Message from %s in chat %s text=%s", user_id, chat_id, (text or "")[:100])

    if text and text.startswith("/start"):
        ensure_user_doc(user_id)
        send_message(chat_id, f"👋 Welcome! You get <b>{FREE_LIMIT}</b> free videos. Use the menu below.", reply_markup=build_main_menu())
        return

    if text and text.lower() in ("videos", "video"):
        await _send_video_flow(chat_id, user_id)
        return

    send_message(chat_id, "I didn't understand. Use the menu.", reply_markup=build_main_menu())

async def _handle_callback(cb: Dict[str, Any]):
    data = cb.get("data", "")
    callback_id = cb.get("id")
    from_user = cb.get("from") or {}
    user_id = from_user.get("id")
    message = cb.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    logger.info("Callback received: %s from user %s", data, user_id)

    # acknowledge to remove spinner
    answer_callback(callback_id)

    parts = data.split(":", 1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "videos":
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "next":
        increment_cursor(user_id)
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "watch_ad":
        session = create_ad_session(user_id)
        # create open-url (shortened if possible)
        open_url = create_ad_open_url(session["token"], user_id)
        keyboard = {"inline_keyboard": [
            [{"text": "Watch ad (open)", "url": open_url}],
            [{"text": "I watched", "callback_data": f"iwatched:{session['token']}"}]
        ]}
        send_message(chat_id, "Open the ad then press 'I watched' only after real completion.", reply_markup=keyboard)
        return
    if cmd == "iwatched":
        token = arg
        session = ad_sessions_col.find_one({"token": token, "user_id": user_id})
        if not session:
            send_message(chat_id, "Ad session not found. Please try Watch Ad again.")
            return
        if session.get("completed"):
            users_col.update_one({"user_id": user_id}, {"$set": {"free_remaining": FREE_LIMIT, "cursor": 0}})
            send_message(chat_id, "✅ Verified. You got another set of free videos. Sending one now.")
            await _send_video_flow(chat_id, user_id)
        else:
            send_message(chat_id, "🔒 We couldn't verify ad completion yet. Please wait a few seconds after watching. If you used a shortener, ensure it calls back to our server.")
        return

    send_message(chat_id, "Unknown action", reply_markup=build_main_menu())

async def _send_video_flow(chat_id: int, user_id: int):
    u = ensure_user_doc(user_id)
    free_remaining = u.get("free_remaining", FREE_LIMIT)
    cursor = u.get("cursor", 0)

    if free_remaining <= 0:
        session = create_ad_session(user_id)
        kb = {"inline_keyboard": [
            [{"text": "Watch Ad to get more videos", "callback_data": f"watch_ad:{session['token']}"}],
            [{"text": "Join Group", "url": REQUIRED_GROUP_LINK}]
        ]}
        send_message(chat_id, "You used your free videos. Watch an ad to get more.", reply_markup=kb)
        return

    doc = get_next_video_for_user(user_id)
    if not doc:
        send_message(chat_id, "❌ No videos found in DB.")
        return

    file_id = doc.get("file_id")
    caption = doc.get("caption", "") or ""
    # safe caption shorten & strip newlines (avoid f-string backslash)
    safe_caption = (caption[:300].replace("\n", " "))

    kb = {"inline_keyboard": [
        [{"text": "⏭ Next", "callback_data": "next:0"}],
        [{"text": "📢 Watch Ad (to refill)", "callback_data": f"watch_ad:auto"}],
        [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}]
    ]}

    if file_id:
        send_video(chat_id, file_id, caption=safe_caption, reply_markup=kb)
    else:
        send_message(chat_id, f"{safe_caption}\n\n(File not stored on bot.)", reply_markup=kb)

    users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
