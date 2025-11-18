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
    BOT_TOKEN,
    MONGO_URL,
    MONGO_DB_NAME,
    FREE_LIMIT,
    REQUIRED_GROUP_LINK,
    AD_PROVIDER_URL,
    SHORTLINK_API_KEY,
    SHORTLINK_API_URL,
    DOMAIN,
    LOG_LEVEL,
    # optional control: if true, DO NOT use shortener so advertiser domain stays visible
    SHORTLINK_PREFER_NO_SHORTENING
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")

if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]

videos_col = db.get_collection("videos")
users_col = db.get_collection("users")
ad_sessions_col = db.get_collection("ad_sessions")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

def tg_request(method: str, payload: Dict[str, Any], timeout: float = 10.0):
    url = urljoin(TELEGRAM_API, method)
    try:
        logger.debug("TG REQ -> %s payload keys=%s", url, list(payload.keys()))
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
    cursor = u.get("cursor", 0)
    doc_cursor = videos_col.find().sort("_id", -1).skip(cursor).limit(1)
    docs = list(doc_cursor)
    if not docs:
        return None
    return docs[0]

def increment_cursor(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"cursor": 1}})

async def create_shortlink(target_url: str) -> str:
    """
    Create a shortlink using SHORTLINK_API_KEY + SHORTLINK_API_URL.
    If shortener not configured or fails, return original target_url.
    """
    if not SHORTLINK_API_KEY or not SHORTLINK_API_URL:
        logger.info("SHORTLINK not configured, returning original url")
        return target_url

    payload = {"api": SHORTLINK_API_KEY, "url": target_url}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(SHORTLINK_API_URL, data=payload, timeout=10)
        text = r.text or ""
        logger.debug("shortlink response status=%s body=%s", r.status_code, text[:1000])
        j = r.json()
        if isinstance(j, dict):
            if j.get("status") in ("success", "ok") and j.get("shortenedUrl"):
                return j["shortenedUrl"]
            if j.get("short"):
                return j["short"]
            if j.get("result") and isinstance(j["result"], str):
                return j["result"]
        if r.status_code == 200 and text.startswith("http"):
            return text.strip()
    except Exception as exc:
        logger.exception("shortlink creation failed: %s", exc)

    return target_url

async def create_ad_session(user_id: int):
    """
    Build advertiser-target URL (the one user should open to view ad).
    Rules:
      - If AD_PROVIDER_URL contains the placeholder {return_url}, substitute it.
      - Else append ?return=... or &return=... depending on presence of ?.
      - Then either shorten that target (if shortener enabled and SHORTLINK_PREFER_NO_SHORTENING not true)
        or return the raw target so the advertiser domain is visible.
    """
    token = str(uuid.uuid4())
    raw_return = f"{DOMAIN.rstrip('/')}/ad/return?token={token}&uid={user_id}"

    provider_template = AD_PROVIDER_URL or REQUIRED_GROUP_LINK
    # build target that goes to advertiser and then later returns to our raw_return
    if "{return_url}" in provider_template:
        ad_target = provider_template.replace("{return_url}", raw_return)
    else:
        if "?" in provider_template:
            ad_target = f"{provider_template}&return={raw_return}"
        else:
            ad_target = f"{provider_template}?return={raw_return}"

    # Decide whether to short the ad_target. If the env asks to prefer no shortening,
    # keep advertiser domain visible. Otherwise, shorten (shortxlinks domain will show).
    shortener_disabled = str(os.getenv("SHORTLINK_PREFER_NO_SHORTENING", SHORTLINK_PREFER_NO_SHORTENING or "")).lower() in ("1","true","yes")
    if SHORTLINK_API_KEY and not shortener_disabled:
        provider_url = await create_shortlink(ad_target)
    else:
        provider_url = ad_target

    doc = {
        "token": token,
        "user_id": user_id,
        "provider_url": provider_url,
        "ad_target": ad_target,
        "completed": False,
        "created_at": int(time.time())
    }
    ad_sessions_col.insert_one(doc)
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

    if text and text.lower() in ("videos", "video"):
        await _send_video_flow(chat_id, user_id)
        return

    if text and text.startswith("/list_videos"):
        docs = list(videos_col.find().sort("_id", -1).limit(50))
        if not docs:
            send_message(chat_id, "No videos in DB.")
            return
        out_lines: List[str] = []
        for d in docs:
            vidid = str(d.get("_id"))[:8]
            has_file = "yes" if d.get("file_id") else "no"
            caption_snip = (d.get("caption", "")[:60]).replace("\n", " ")
            out_lines.append(f"- id:{vidid} file_id:{has_file} caption:{caption_snip}")
        chunks = ["\n".join(out_lines[i:i+10]) for i in range(0, len(out_lines), 10)]
        for c in chunks:
            send_message(chat_id, f"<pre>{c}</pre>")
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
        session = await create_ad_session(user_id)
        keyboard = {
            "inline_keyboard": [
                [{"text": "Watch ad (open)", "url": session["provider_url"]}],
                [{"text": "I watched", "callback_data": f"iwatched:{session['token']}"}]
            ]
        }
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

    if free_remaining <= 0:
        session = await create_ad_session(user_id)
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
