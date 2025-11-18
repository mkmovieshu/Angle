# app/telegram/handlers.py
import os
import logging
import uuid
import time
import json
from typing import Dict, Any, Optional

import httpx
from pymongo import MongoClient
from urllib.parse import urljoin

logger = logging.getLogger(__name__)
# Ensure root logger prints to stdout on Render
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)
else:
    logging.getLogger().setLevel(logging.INFO)

# Env requirements (follow your naming: MONGO_URL not MONGO_URI)
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

AD_PROVIDER_URL = os.getenv("AD_PROVIDER_URL", REQUIRED_GROUP_LINK)

# Optional admin check (comma separated IDs) to protect debug commands
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
}

# Mongo
client = MongoClient(MONGO_URL)
db = client[DB_NAME]

videos_col = db.get_collection("videos")
users_col = db.get_collection("users")
ad_sessions_col = db.get_collection("ad_sessions")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

def tg_request(method: str, payload: Dict[str, Any], timeout: float = 10.0):
    """
    Wrapper for Telegram API calls.
    Returns parsed JSON on success, or the error JSON (if parseable), or None on network failure.
    Always logs full status + JSON body for debugging.
    """
    url = urljoin(TELEGRAM_API, method)
    try:
        logger.info("TG REQ -> %s payload keys=%s", url, list(payload.keys()))
        r = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        logger.exception("tg_request network error %s %s", url, exc)
        return None

    text = r.text or ""
    # log full body up to a generous limit
    body_preview = text[:4000]
    logger.info("tg_request response status=%s body=%s", r.status_code, body_preview)

    try:
        j = r.json()
    except Exception:
        logger.error("tg_request: response is not JSON (status %s). body=%s", r.status_code, body_preview)
        return None

    if not j.get("ok", False):
        # Log error JSON so you can see exact Telegram error.
        logger.error("Telegram API returned error: %s", json.dumps(j, indent=2)[:4000])
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

    logger.info("Sending video -> chat=%s file_id(len)=%d caption_len=%d", cid, len(str(file_id)), len(caption or ""))
    resp = tg_request("sendVideo", payload)
    # If Telegram returned an error JSON, log it fully (already logged in tg_request)
    return resp

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
    doc = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc)
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

# exported function used by routes.py
async def handle_update(data: Dict[str, Any]):
    """
    Accepts either:
      - dict update from webhook (normal),
      - or objects that have to_dict() (e.g., python-telegram-bot Update).
    This normalizes the incoming payload to a plain dict and routes.
    """
    # Normalize if data is an object (telegram.Update) or nested payload
    try:
        # If it's not a dict, try to convert via to_dict()
        if not isinstance(data, dict):
            to_dict = getattr(data, "to_dict", None)
            if callable(to_dict):
                logger.debug("Converting Update object to dict via to_dict()")
                data = to_dict()
            else:
                # fallback: try to JSON roundtrip (best-effort)
                try:
                    data = json.loads(json.dumps(data, default=lambda o: getattr(o, "__dict__", str(o))))
                except Exception:
                    logger.warning("Couldn't normalize update object; logging type: %s", type(data))
                    data = {"raw": str(data)}
    except Exception:
        logger.exception("Failed to normalize incoming update")

    # Some webhook providers wrap update inside another key (rare). Unwrap common pattern.
    if "update_id" in data and len(data) > 1:
        # it's fine; proceed
        pass
    elif "update_id" in data and len(data) == 1:
        # weird wrapper; try to extract nested dict if present
        for k, v in list(data.items()):
            if isinstance(v, dict) and k != "update_id":
                data = v
                break

    # Primary routing
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    elif "inline_query" in data:
        logger.info("Inline query ignored")
    else:
        logger.info("Unhandled update type: %s keys=%s", type(data), list(data.keys())[:10])

async def _handle_message(msg: Dict[str, Any]):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    text = msg.get("text", "")

    logger.info("Message from %s in chat %s text=%s", user_id, chat_id, (text or "")[:200])

    if text and text.startswith("/start"):
        ensure_user_doc(user_id)
        send_message(chat_id, f"👋 Welcome! You get <b>{FREE_LIMIT}</b> free videos. Use the menu below.", reply_markup=build_main_menu())
        return

    # Debug admin command to inspect DB (only for admins if ADMIN_USER_IDS set)
    if text and text.startswith("/db_videos"):
        if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
            send_message(chat_id, "Not allowed.")
            return
        count = videos_col.count_documents({})
        sample = list(videos_col.find().sort("_id", -1).limit(5))
        lines = [f"videos_count: {count}"]
        for d in sample:
            lines.append(f"- id:{str(d.get('_id'))[:8]} file:{d.get('file_id') or 'NO_FILE'} caption:{(d.get('caption') or '')[:60]}")
        send_message(chat_id, "\n".join(lines))
        return

    if text and text.lower() in ("videos", "video"):
        await _send_video_flow(chat_id, user_id)
        return

    send_message(chat_id, "I didn't understand. Use the menu.", reply_markup=build_main_menu())

async def _handle_callback(cb: Dict[str, Any]):
    data = cb.get("data", "")
    if isinstance(data, str):
        data = data.strip()
    callback_id = cb.get("id")
    from_user = cb.get("from") or {}
    user_id = from_user.get("id")
    message = cb.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    logger.info("Callback received: %s from user %s", data, user_id)

    # acknowledge to remove spinner
    answer_callback(callback_id)

    parts = (data or "").split(":", 1)
    cmd = parts[0].strip()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "videos":
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "next":
        increment_cursor(user_id)
        await _send_video_flow(chat_id, user_id)
        return
    if cmd == "watch_ad":
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
    caption = doc.get("caption", "")
    kb = {"inline_keyboard": [
        [{"text": "⏭ Next", "callback_data": "next:0"}],
        [{"text": "📢 Watch Ad (to refill)", "callback_data": f"watch_ad:auto"}],
        [{"text": "➡️ Join Group", "url": REQUIRED_GROUP_LINK}]
    ]}

    if file_id:
        resp = send_video(chat_id, file_id, caption=caption, reply_markup=kb)
        # If Telegram returned an error JSON, include error text to user (for debugging)
        if resp and not resp.get("ok", True):
            err = resp.get("description") or str(resp)
            send_message(chat_id, f"❗️Failed to send video: {err}")
    else:
        send_message(chat_id, f"{caption}\n\n(File not stored on bot.)", reply_markup=kb)

    users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
