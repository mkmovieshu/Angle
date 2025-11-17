# app/telegram/handlers.py
import os
import logging
import uuid
import time
from typing import Dict, Any, Optional

import httpx
from pymongo import MongoClient
from urllib.parse import urljoin

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

# Optional ad provider URL shown to user (replace with real short link provider if available)
AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Mongo
client = MongoClient(MONGO_URL)
db = client[DB_NAME]

videos_col = db.get_collection("videos")           # expected schema: { _id, file_id, caption, source_channel_id, created_at }
users_col = db.get_collection("users")             # { user_id, free_remaining, cursor, joined }
ad_sessions_col = db.get_collection("ad_sessions") # { token, user_id, provider_url, completed, created_at }

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

def tg_request(method: str, payload: Dict[str, Any]):
    url = urljoin(TELEGRAM_API, method)
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.exception("tg_request failed %s %s", url, exc)
        return None

def send_message(chat_id: int, text: str, reply_markup: Optional[Dict]=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_request("sendMessage", payload)

def send_video(chat_id: int, file_id: str, caption: str = "", reply_markup: Optional[Dict]=None):
    payload = {"chat_id": chat_id, "video": file_id}
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

def build_main_menu():
    keyboard = {
        "inline_keyboard": [
            [{"text": "📺 Videos", "callback_data": "videos:0"}],
            [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}],
        ]
    }
    return keyboard

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
    # get one video at cursor position (sorted by _id desc to show newest first)
    doc = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc)
    if not docs:
        return None
    return docs[0]

def increment_cursor(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"cursor": 1}})

def create_ad_session(user_id: int):
    token = str(uuid.uuid4())
    provider_url = AD_PROVIDER_URL  # ideally dynamic
    doc = {
        "token": token,
        "user_id": user_id,
        "provider_url": provider_url,
        "completed": False,
        "created_at": int(time.time())
    }
    ad_sessions_col.insert_one(doc)
    return doc

# exported function used by routes.py
async def handle_update(data: Dict[str, Any]):
    """
    Entry point called by routes when a webhook arrives.
    Accepts the raw update dict (telegram JSON).
    """
    # Telegram python lib Update objects might come though as dict-like; handle both.
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    elif "inline_query" in data:
        # not used currently
        logger.info("Inline query ignored")
    else:
        logger.info("Unhandled update type: %s", type(data))

async def _handle_message(msg: Dict[str, Any]):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    text = msg.get("text", "")

    if text and text.startswith("/start"):
        # reset cursor optionally or keep persistent
        ensure_user_doc(user_id)
        send_message(chat_id, f"👋 Welcome! You get <b>{FREE_LIMIT}</b> free videos. Use the menu below.", reply_markup=build_main_menu())
        return

    # if user sends a plain message, treat as request for video
    if text and text.lower() in ("videos", "video"):
        await _send_video_flow(chat_id, user_id)
        return

    # handle other messages
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

    # Example callback_data patterns:
    # videos:0  (start)
    # next:<nothing> handled by increment
    # watch_ad:<token>
    # iwatched:<token>
    parts = data.split(":", 1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    # Acknowledge callback quickly to avoid 'loading' spinner
    answer_callback(callback_id)

    if cmd == "videos":
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "next":
        # send next video (advance cursor)
        increment_cursor(user_id)
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "watch_ad":
        # create ad session and send URL button
        session = create_ad_session(user_id)
        keyboard = {"inline_keyboard": [[{"text": "Watch ad (open)", "url": session["provider_url"]}], [{"text": "I watched", "callback_data": f"iwatched:{session['token']}"}]]}
        send_message(chat_id, "Open the ad then press 'I watched' only after real completion.", reply_markup=keyboard)
        return
    if cmd == "iwatched":
        token = arg
        session = ad_sessions_col.find_one({"token": token, "user_id": user_id})
        if not session:
            send_message(chat_id, "Ad session not found. Please try Watch Ad again.")
            return
        # IMPORTANT: Security note - provider should call back to mark completed.
        # Here we only trust provider callback; do NOT allow immediate bypass.
        if session.get("completed"):
            # mark user's free_remaining and continue
            users_col.update_one({"user_id": user_id}, {"$set": {"free_remaining": FREE_LIMIT, "cursor": 0}})
            send_message(chat_id, "✅ Verified. You got another set of free videos. Sending one now.")
            await _send_video_flow(chat_id, user_id)
        else:
            send_message(chat_id, "🔒 We couldn't verify ad completion yet. Please wait a few seconds after watching. If you used a shortener, ensure it calls back to our server.")
        return

    # default fallback
    send_message(chat_id, "Unknown action", reply_markup=build_main_menu())

async def _send_video_flow(chat_id: int, user_id: int):
    u = ensure_user_doc(user_id)
    free_remaining = u.get("free_remaining", FREE_LIMIT)
    cursor = u.get("cursor", 0)

    if free_remaining <= 0:
        # require watching ad
        session = create_ad_session(user_id)
        kb = {"inline_keyboard": [
            [{"text": "Watch Ad to get more videos", "callback_data": f"watch_ad:{session['token']}"}],
            [{"text": "Join Group", "url": REQUIRED_GROUP_LINK}]
        ]}
        send_message(chat_id, "You used your free videos. Watch an ad to get more.", reply_markup=kb)
        return

    # get next video doc
    doc = get_next_video_for_user(user_id)
    if not doc:
        send_message(chat_id, "❌ No videos found in DB.")
        return

    file_id = doc.get("file_id")
    caption = doc.get("caption", "")
    # build inline keyboard for next / watch ad / join group
    kb = {"inline_keyboard": [
        [{"text": "⏭ Next", "callback_data": "next:0"}],
        [{"text": "📢 Watch Ad (to refill)", "callback_data": f"watch_ad:auto"}],
        [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}]
    ]}

    # send actual video
    if file_id:
        send_video(chat_id, file_id, caption=caption, reply_markup=kb)
    else:
        # fallback: message with link/source
        send_message(chat_id, f"{caption}\n\n(File not stored on bot.)", reply_markup=kb)

    # consume one free
    users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
