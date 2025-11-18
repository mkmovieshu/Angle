# app/telegram/handlers.py
import os
import logging
import uuid
import time
from typing import Dict, Any, Optional, List

import httpx
from pymongo import MongoClient
from urllib.parse import urljoin, urlencode

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

# you insisted on MONGO_URL name
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))

REQUIRED_GROUP_ID = os.getenv("REQUIRED_GROUP_ID")  # optional
REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "https://t.me/your_group")

AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", "https://example-ad-provider.local/landing")
# Admins (comma separated list of numeric Telegram user ids)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# Mongo
client = MongoClient(MONGO_URL)
db = client[DB_NAME]

videos_col = db.get_collection("videos")
users_col = db.get_collection("users")
ad_sessions_col = db.get_collection("ad_sessions")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

def tg_request(method: str, payload: Dict[str, Any], timeout: float = 10.0):
    url = urljoin(TELEGRAM_API, method)
    try:
        logger.debug("TG REQUEST %s %s", url, payload)
        r = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        logger.exception("tg_request network error %s %s", url, exc)
        return None

    text = r.text or ""
    logger.info("tg_request response status=%s body=%s", r.status_code, text[:2000])

    try:
        j = r.json()
    except Exception:
        logger.error("tg_request: response is not JSON (status %s). body=%s", r.status_code, text[:2000])
        return None

    if not j.get("ok", False):
        logger.error("Telegram API returned error: %s", j)
        return j

    return j

def safe_int_chat_id(chat_id):
    try:
        return int(chat_id)
    except Exception:
        return None

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
    cursor = int(u.get("cursor", 0))
    total = videos_col.count_documents({})
    if total == 0:
        return None
    if cursor >= total:
        # wrap around to beginning
        users_col.update_one({"user_id": user_id}, {"$set": {"cursor": 0}})
        cursor = 0
    doc = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc)
    if not docs:
        return None
    return docs[0]

def increment_cursor(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"cursor": 1}})

def create_ad_session(user_id: int):
    token = str(uuid.uuid4())
    # attach token as param so provider (or shortener) can notify our server with same token
    provider_url = AD_PROVIDER_URL
    # make sure token is passed to provider landing page
    if "?" in provider_url:
        provider_url = f"{provider_url}&token={token}"
    else:
        provider_url = f"{provider_url}?token={token}"

    doc = {
        "token": token,
        "user_id": user_id,
        "provider_url": provider_url,
        "completed": False,
        "created_at": int(time.time())
    }
    ad_sessions_col.insert_one(doc)
    logger.info("Created ad session %s for user %s", token, user_id)
    return doc

# NOTE: provider must call our server to mark session completed.
# Example: POST /ads/complete with JSON {"token": "<token>"}  (see instructions below)

# exported function used by routes.py
async def handle_update(data: Dict[str, Any]):
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    elif "inline_query" in data:
        logger.info("Inline query ignored")
    else:
        logger.info("Unhandled update type: %s", type(data))

async def _handle_message(msg: Dict[str, Any]):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    text = (msg.get("text") or "").strip()

    logger.info("Message from %s in chat %s text=%s", user_id, chat_id, (text or "")[:100])

    if not user_id:
        logger.warning("Message without user id: %s", msg)
        return

    if text.startswith("/start"):
        ensure_user_doc(user_id)
        send_message(chat_id, f"👋 Welcome! You get <b>{FREE_LIMIT}</b> free videos. Use the menu below.", reply_markup=build_main_menu())
        return

    # admin helper to inspect DB
    if text.startswith("/db_stats"):
        if user_id not in ADMIN_IDS:
            send_message(chat_id, "You are not allowed to run this command.")
            return
        total_videos = videos_col.count_documents({})
        sample = list(videos_col.find().sort("_id", -1).limit(5))
        sample_lines = []
        for s in sample:
            fid = s.get("file_id") or s.get("file_url") or "<no-file>"
            cap = (s.get("caption") or "")[:80].replace("\n", " ")
            sample_lines.append(f"- {fid} | {cap}")
        body = f"Videos: {total_videos}\n\nSample:\n" + ("\n".join(sample_lines) if sample_lines else "none")
        send_message(chat_id, body)
        return

    if text.lower() in ("videos", "video"):
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

    # acknowledge to remove spinner quickly
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
        # always create a fresh session and force user to open provider_url (provider must call our webhook)
        session = create_ad_session(user_id)
        keyboard = {
            "inline_keyboard": [
                [{"text": "Open Ad (open)", "url": session["provider_url"]}],
                [{"text": "I watched (verify)", "callback_data": f"iwatched:{session['token']}"}]
            ]
        }
        send_message(chat_id, "Open the ad page and complete it. Only after the provider notifies us will verification succeed. Press 'I watched' only after you actually finished watching.", reply_markup=keyboard)
        return

    if cmd == "iwatched":
        token = arg
        session = ad_sessions_col.find_one({"token": token, "user_id": user_id})
        if not session:
            send_message(chat_id, "Ad session not found. Please try 'Watch Ad' again.")
            return

        # Strict: we only accept if provider has called our server and set completed=True
        if session.get("completed"):
            # refill
            users_col.update_one({"user_id": user_id}, {"$set": {"free_remaining": FREE_LIMIT, "cursor": 0}})
            send_message(chat_id, "✅ Verified by provider. You got another set of free videos. Sending one now.")
            await _send_video_flow(chat_id, user_id)
        else:
            # don't give benefit-of-doubt. require provider callback.
            send_message(chat_id, "🔒 We couldn't verify ad completion yet. The ad provider must notify us. If you already finished, wait a few seconds and try again. If using a shortener, ensure it calls our callback endpoint.")
        return

    send_message(chat_id, "Unknown action", reply_markup=build_main_menu())

async def _send_video_flow(chat_id: int, user_id: int):
    u = ensure_user_doc(user_id)
    free_remaining = int(u.get("free_remaining", FREE_LIMIT))
    cursor = int(u.get("cursor", 0))

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
    caption = doc.get("caption", "")
    kb = {"inline_keyboard": [
        [{"text": "⏭ Next", "callback_data": "next:0"}],
        [{"text": "📢 Watch Ad (to refill)", "callback_data": "watch_ad:auto"}],
        [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}]
    ]}

    if file_id:
        resp = send_video(chat_id, file_id, caption=caption, reply_markup=kb)
        # only decrement after successful send
        if resp and isinstance(resp, dict) and resp.get("ok", False):
            users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
            logger.info("Sent video to user %s, decremented free_remaining", user_id)
        else:
            logger.error("Failed to send video to user %s, response=%s", user_id, resp)
            send_message(chat_id, "Failed to send video. Please try again later.", reply_markup=build_main_menu())
    else:
        send_message(chat_id, f"{caption}\n\n(File not stored on bot.)", reply_markup=kb)
        # still decrement because we showed content
        users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
