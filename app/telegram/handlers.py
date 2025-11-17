# app/telegram/handlers.py
import os
import asyncio
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram import Message
from telegram.ext import ContextTypes  # optional; not required

from pymongo import MongoClient

# local imports
from app.config import BOT_TOKEN, MONGO_URL, BIN_CHANNEL, FREE_LIMIT, ADMIN_CONTACT, DOMAIN, PREMIUM_PLANS
from app.telegram.keyboards import free_video_nav, ad_prompt_buttons, premium_plan_buttons

# Ads service (should exist)
try:
    from app.ads.service import create_ad_session, get_session, mark_ad_completed
except Exception:
    # fallback stubs if ads.service missing — better to have real one
    def create_ad_session(user_id, provider=None, dest_url=None):
        return {"token": "adstub" + str(user_id), "short_url": None, "provider_payload": None}
    def get_session(token):
        return None
    def mark_ad_completed(token, provider_payload=None):
        return False

bot = Bot(token=BOT_TOKEN)

# Setup DB
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = client.get_default_database() or client["video_web_bot"]
users_col = db.get_collection("users")
videos_col = db.get_collection("videos")
ad_sessions_col = db.get_collection("ad_sessions")

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# --- helper db functions ---
def ensure_user_doc(user_id: int, username: Optional[str] = None, name: Optional[str] = None):
    """
    Ensure a user document exists. Fields:
      user_id, username, name, free_count, last_seen_index, premium_until, seen_videos (list)
    """
    u = users_col.find_one({"user_id": int(user_id)})
    if not u:
        doc = {
            "user_id": int(user_id),
            "username": username,
            "name": name,
            "free_count": 0,
            "last_seen_index": -1,  # index in videos collection or in bin
            "seen_videos": [],  # list of file_ids or message_ids shown
            "premium_until": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        users_col.insert_one(doc)
        return doc
    # update possible username/name
    update = {}
    if username and u.get("username") != username:
        update["username"] = username
    if name and u.get("name") != name:
        update["name"] = name
    if update:
        update["updated_at"] = now_iso()
        users_col.update_one({"user_id": int(user_id)}, {"$set": update})
        u = users_col.find_one({"user_id": int(user_id)})
    return u

def increment_free_count(user_id: int, incr: int = 1):
    users_col.update_one({"user_id": int(user_id)}, {"$inc": {"free_count": incr}, "$set": {"updated_at": now_iso()}})

def reset_free_count(user_id: int):
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"free_count": 0, "updated_at": now_iso()}})

def add_seen_video(user_id: int, file_id: str):
    users_col.update_one({"user_id": int(user_id)}, {"$push": {"seen_videos": file_id}, "$set": {"updated_at": now_iso()}})

def is_premium(user_doc: dict):
    pu = user_doc.get("premium_until")
    if not pu:
        return False
    try:
        # store premium_until as ISO string
        from datetime import datetime
        exp = datetime.fromisoformat(pu)
        return exp > datetime.utcnow()
    except Exception:
        return False

# --- video retrieval from BIN channel ---
def get_videos_from_bin(limit: int = 50):
    """
    This function assumes that you have populated 'videos' collection
    with metadata (file_id or message_id and caption).
    If you rely on reading directly from BIN_CHANNEL using bot.forward or get_chat_history,
    implement that logic here.
    """
    # prefer videos collection if prefilled
    docs = list(videos_col.find().sort("created_at", -1).limit(limit))
    return docs

# --- UI helpers ---
async def send_video_message(chat_id: int, file_id: str, caption: str = None, reply_markup: InlineKeyboardMarkup = None):
    """
    Send video by file_id (file_id stored in DB or message_id from channel).
    """
    try:
        # If file_id is a Telegram file_id (video), use send_video
        # If it's a message_id from channel, use copy_message
        if file_id.isdigit():
            # treat as message_id from BIN channel
            await bot.copy_message(chat_id=chat_id, from_chat_id=BIN_CHANNEL, message_id=int(file_id), caption=caption or "")
        else:
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption or "", reply_markup=reply_markup)
    except Exception as e:
        # fallback: try send_message with a link or text
        try:
            await bot.send_message(chat_id=chat_id, text=(caption or "Video"), reply_markup=reply_markup)
        except Exception:
            pass

# --- core: send next video to user respecting free limit/premium/ad ---
async def send_next_video_to_user(chat_id: int, user_id: int):
    """
    Sends next video according to user's state:
    - if premium -> give next unlimited video
    - else if free_count < FREE_LIMIT -> give next free video and increment
    - else -> ask to watch ad or buy premium (show inline buttons)
    """
    user = ensure_user_doc(user_id)
    # premium?
    if is_premium(user):
        # send next available video (no limit)
        docs = get_videos_from_bin(limit=1)
        if not docs:
            await bot.send_message(chat_id=chat_id, text="No videos available right now.")
            return
        doc = docs[0]
        file_id = str(doc.get("message_id") or doc.get("file_id") or "")
        caption = doc.get("caption") or ""
        # send with normal next button (still allow next)
        await send_video_message(chat_id, file_id, caption=caption, reply_markup=free_video_nav("next_premium"))
        add_seen_video(user_id, file_id)
        return

    # not premium
    fc = int(user.get("free_count", 0))
    if fc < FREE_LIMIT:
        # serve next free video
        # choose a video not yet seen by user if possible
        seen = set(user.get("seen_videos", []) or [])
        all_videos = get_videos_from_bin(limit=100)
        next_doc = None
        for d in all_videos:
            fid = str(d.get("message_id") or d.get("file_id") or "")
            if fid not in seen:
                next_doc = d
                break
        if not next_doc and all_videos:
            next_doc = all_videos[0]  # fallback
        if not next_doc:
            await bot.send_message(chat_id=chat_id, text="No videos available.")
            return
        file_id = str(next_doc.get("message_id") or next_doc.get("file_id") or "")
        caption = next_doc.get("caption") or ""
        # prepare next button payload; if after incrementing this reaches FREE_LIMIT will be handled next call
        await send_video_message(chat_id, file_id, caption=caption, reply_markup=free_video_nav("next_free"))
        # update user state
        increment_free_count(user_id, 1)
        add_seen_video(user_id, file_id)
        return

    # fc >= FREE_LIMIT -> show ad prompt buttons
    # create ad session so Watch Ad button has a token/redirect we control
    ad = create_ad_session(user_id=user_id, provider=None, dest_url=None)
    token = ad.get("token")
    # use domain if present to build redirect
    kb = ad_prompt_buttons(token=token, domain=DOMAIN)
    # replace Contact Admin button URL properly with ADMIN_CONTACT
    # If admin contact is a username like @admin, convert to t.me link
    if kb.inline_keyboard and kb.inline_keyboard[-1]:
        try:
            admin_url = ADMIN_CONTACT
            if admin_url.startswith("@"):
                admin_url = f"https://t.me/{admin_url.lstrip('@')}"
            kb.inline_keyboard[-1][0] = InlineKeyboardButton("Contact Admin", url=admin_url)
        except Exception:
            pass
    # send prompt
    await bot.send_message(chat_id=chat_id, text=f"మీ ఫ్రీ వీడియోలు ముగిశాయి. మరింత వీడియోలు చూడటానికి ఒక చిన్న యాడ్ చూడండి లేదా ప్రీమియం తీసుకోండి.", reply_markup=kb)

# --- webhook / update handlers (basic) ---
async def handle_update(data: dict):
    """
    Entrypoint called from routes/webhook: forwards messages and callback_queries to handlers below.
    """
    # Telegram update object contains various fields
    if "message" in data:
        message = data["message"]
        # basic start handling
        if "text" in message and message["text"].startswith("/start"):
            chat = message["chat"]
            user = message["from"]
            uid = int(user["id"])
            # ensure doc
            ensure_user_doc(uid, username=user.get("username"), name=user.get("first_name"))
            # greet + show first free video button
            txt = "Welcome to ANGEL! మైకే మీరు మొదటికైనా ఫ్రీ వీడియోలు చూడవచ్చు."
            # show a button "Free Video" which triggers next video via callback (or user can send /getfree)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Free Video", callback_data="next_free")]])
            await bot.send_message(chat_id=chat["id"], text=txt, reply_markup=kb)
            return

        # normal message text request to get a video immediately
        if "text" in message and message["text"].lower().strip() in ("free", "video", "get video"):
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            await send_next_video_to_user(chat_id, user_id)
            return

    if "callback_query" in data:
        cq = data["callback_query"]
        data_payload = cq.get("data")
        user = cq["from"]
        chat_id = cq["message"]["chat"]["id"]
        user_id = user["id"]
        # Acknowledge (answerCallbackQuery) to avoid spinner — using Bot method
        try:
            await bot.answer_callback_query(callback_query_id=cq["id"])
        except Exception:
            pass

        # handle known payloads
        if data_payload == "next_free":
            await send_next_video_to_user(chat_id, user_id)
            return
        if data_payload == "create_ad":
            # create ad session and send a clickable URL
            ad = create_ad_session(user_id=user_id, provider=None, dest_url=None)
            token = ad.get("token")
            url = f"{DOMAIN}/ad/redirect/{token}" if DOMAIN else None
            if url:
                await bot.send_message(chat_id=chat_id, text=f"Please open this link to watch ad and return: {url}")
            else:
                await bot.send_message(chat_id=chat_id, text="Unable to create ad link right now. Contact admin.")
            return
        if data_payload == "get_premium":
            # show plan buttons with admin contact
            kb = premium_plan_buttons(ADMIN_CONTACT)
            await bot.send_message(chat_id=chat_id, text="Choose a premium plan or contact admin to buy.", reply_markup=kb)
            return
        if data_payload.startswith("buy_"):
            plan = data_payload.split("_", 1)[1]
            # map to days
            days = {"10": 10, "20": 20, "30": 30}.get(plan)
            if days:
                # instruct to contact admin or pay via UPI — simplified flow
                await bot.send_message(chat_id=chat_id, text=f"To buy {days} days premium, contact admin: https://t.me/{ADMIN_CONTACT.lstrip('@')}")
            else:
                await bot.send_message(chat_id=chat_id, text="Invalid plan.")
            return

    # ignore other update types for now
    return

# Optionally: a small endpoint handler (not used here) that gets called when ad provider redirects back
# Example: when user finishes ad, provider redirects to /ad/complete/<token> which would call mark_ad_completed(token)
# You already have ads/service.create_ad_session — ensure that route marks completed and triggers giving next videos.
