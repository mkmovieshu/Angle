# app/telegram/handlers.py
import os
import logging
import uuid
import time
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

import httpx
from pymongo import MongoClient
from urllib.parse import urljoin

from app.config import (
    BOT_TOKEN, MONGO_URL, MONGO_DB_NAME, FREE_LIMIT,
    REQUIRED_GROUP_LINK, SHORTLINK_API_KEY, SHORTLINK_API_BASE,
    DOMAIN, ADMIN_USERS, AD_PROVIDER_URL
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Mongo client & collections
client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]

videos_col = db.get_collection("videos")
users_col = db.get_collection("users")
ad_sessions_col = db.get_collection("ad_sessions")

def tg_request(method: str, payload: Dict[str, Any], timeout: float = 10.0):
    url = urljoin(TELEGRAM_API, method)
    try:
        logger.debug("TG REQ -> %s payload keys=%s", url, list(payload.keys()))
        r = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        logger.exception("tg_request network error %s %s", url, exc)
        return None

    text = r.text or ""
    logger.info("tg_request response status=%s body=%s", r.status_code, (text[:2000] if text else ""))
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
    cursor = u.get("cursor", 0)
    doc_cursor = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc_cursor)
    if not docs:
        return None
    return docs[0]

def increment_cursor(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"cursor": 1}})

def _shorten_with_provider(long_url: str) -> str:
    """
    Use shortxlinks (or other provider) to shorten the long_url if API key provided.
    Falls back to returning long_url if anything fails.
    """
    if not SHORTLINK_API_KEY:
        logger.info("SHORTLINK_API_KEY not set; skipping shortener")
        return long_url
    try:
        params = {"api": SHORTLINK_API_KEY, "url": long_url, "format": "text"}
        api_url = SHORTLINK_API_BASE + "?" + urlencode(params)
        logger.info("Shortener request: %s", api_url)
        r = httpx.get(api_url, timeout=6.0)
        if r.status_code == 200 and r.text:
            short = r.text.strip()
            # shortxlinks returns plaintext short URL in text mode
            logger.info("Shortener returned: %s", short)
            return short
        # fallback: try parse JSON
        try:
            j = r.json()
            if j.get("status") == "success" and j.get("shortenedUrl"):
                return j["shortenedUrl"]
        except Exception:
            logger.warning("Shortener did not return JSON or text")
    except Exception as exc:
        logger.exception("Shortener call failed: %s", exc)
    return long_url

def create_ad_session(user_id: int):
    """
    Create ad session and store provider_url which user will open.
    provider_url will point to a shortlink which redirects to an ad landing page that eventually calls:
      {DOMAIN}/ad/return?token=<token>&uid=<user_id>
    If SHORTLINK_API_KEY present, we shorten the return URL via provider API.
    """
    token = str(uuid.uuid4())
    # Build the return URL that the ad-shortener will redirect back to when complete
    return_url = f"{DOMAIN.rstrip('/')}/ad/return?token={token}&uid={user_id}"
    # If AD_PROVIDER_URL specifically set (like an advertiser) use that as starting point
    # But usually we want a shortlink that first goes to ad network then redirects to return_url.
    # For simplicity we make the shortlink point directly to return_url (so the shortener can be used
    # as the ad destination). If you need a specific provider redirect, set AD_PROVIDER_URL in env.
    if AD_PROVIDER_URL and AD_PROVIDER_URL != REQUIRED_GROUP_LINK:
        # If AD_PROVIDER_URL contains a placeholder like {return} substitute
        if "{return}" in AD_PROVIDER_URL:
            long_target = AD_PROVIDER_URL.replace("{return}", return_url)
        else:
            # Otherwise use return_url as param for provider
            # (provider-specific integration should be configured externally)
            long_target = return_url
    else:
        long_target = return_url

    provider_url = _shorten_with_provider(long_target)
    doc = {
        "token": token,
        "user_id": user_id,
        "provider_url": provider_url,
        "completed": False,
        "created_at": int(time.time())
    }
    ad_sessions_col.insert_one(doc)
    logger.info("Created ad session for %s token=%s provider=%s", user_id, token, provider_url)
    return doc

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
    text = msg.get("text", "")

    logger.info("Message from %s in chat %s text=%s", user_id, chat_id, (text or "")[:100])

    if text and text.startswith("/start"):
        ensure_user_doc(user_id)
        send_message(chat_id, f"👋 Welcome! You get <b>{FREE_LIMIT}</b> free videos. Use the menu below.", reply_markup=build_main_menu())
        return

    # Admin debug commands
    if text and text.startswith("/debug_db"):
        if user_id not in ADMIN_USERS:
            send_message(chat_id, "Unauthorized.")
            return
        # return counts
        vcount = videos_col.count_documents({})
        ucount = users_col.count_documents({})
        acount = ad_sessions_col.count_documents({})
        sample_vid = videos_col.find_one({}, sort=[("_id", -1)])
        sample = {}
        if sample_vid:
            sample = {
                "file_id_present": bool(sample_vid.get("file_id")),
                "caption": sample_vid.get("caption", "")[:200],
                "created_at": sample_vid.get("created_at"),
                "_id": str(sample_vid.get("_id"))
            }
        text_out = (
            f"DB counts — videos={vcount}, users={ucount}, ad_sessions={acount}\n"
            f"Sample latest video: {sample}"
        )
        send_message(chat_id, text_out)
        return

    if text and text.startswith("/list_videos"):
        if user_id not in ADMIN_USERS:
            send_message(chat_id, "Unauthorized.")
            return
        # /list_videos N
        parts = text.strip().split()
        n = 5
        try:
            if len(parts) > 1:
                n = min(50, int(parts[1]))
        except Exception:
            n = 5
        docs = list(videos_col.find().sort("_id", -1).limit(n))
        out_lines = []
        for d in docs:
            out_lines.append(f"- id:{str(d.get('_id'))[:8]} file_id:{'yes' if d.get('file_id') else 'no'} caption:{(d.get('caption','')[:60]).replace('\\n',' ')}")
        send_message(chat_id, "Videos:\n" + "\n".join(out_lines) if out_lines else "No videos found.")
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
        send_video(chat_id, file_id, caption=caption, reply_markup=kb)
    else:
        send_message(chat_id, f"{caption}\n\n(File not stored on bot.)", reply_markup=kb)

    users_col.update_one({"user_id": user_id}, {"$inc": {"free_remaining": -1, "cursor": 1}})
