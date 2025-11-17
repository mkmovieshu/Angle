# app/telegram/handlers.py
import logging
import asyncio
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.telegram.bot import bot  # your Bot instance
from app.config import MONGO_URI, FREE_LIMIT, BIN_CHANNEL, DOMAIN  # adjust names if different

logger = logging.getLogger("uvicorn.error")

# ---------- MongoDB init (fixed boolean-check issue) ----------
client = MongoClient(MONGO_URI)

try:
    default_db = client.get_default_database()
except Exception as e:
    # If get_default_database() raises for some reason, set to None and rely on fallback
    logger.exception("get_default_database() failed, using fallback DB name")
    default_db = None

# use default_db only if it's not None; otherwise fallback to named DB
db = default_db if default_db is not None else client["video_web_bot"]

# Collections (create or get)
users = db.get_collection("users")
videos = db.get_collection("videos")
ad_sessions = db.get_collection("ad_sessions")
logs = db.get_collection("logs")

# ---------- Helper functions ----------
def ensure_user_record(user_id: int, data: dict = None):
    """
    Ensure user document exists. Minimal synchronous helper (safe to call from sync code).
    """
    try:
        user = users.find_one({"user_id": user_id})
        if not user:
            doc = {
                "user_id": user_id,
                "created_at": datetime.utcnow(),
                "free_watched": 0,
                "premium": False,
                "premium_expires": None,
            }
            if data:
                doc.update(data)
            users.insert_one(doc)
            return doc
        return user
    except PyMongoError:
        logger.exception("MongoDB error in ensure_user_record")
        return None

async def send_message_safe(chat_id: int, text: str, reply_markup=None, parse_mode="HTML"):
    """
    Send message using bot and catch exceptions.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramError:
        logger.exception("Failed to send message to %s", chat_id)

# ---------- Ad session helpers (basic) ----------
def create_ad_session(user_id: int, token: str, provider_response: dict = None):
    doc = {
        "user_id": user_id,
        "token": token,
        "created_at": datetime.utcnow(),
        "completed": False,
        "provider_response": provider_response or {},
    }
    res = ad_sessions.insert_one(doc)
    return res.inserted_id

def mark_ad_completed(token: str):
    res = ad_sessions.find_one_and_update(
        {"token": token},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}},
        return_document=True,
    )
    return res

# ---------- Core handlers ----------
async def handle_message(update: dict):
    """
    Legacy-style handler that accepts raw update dict from FastAPI routes.
    This function mirrors earlier codepath: routes -> handle_update -> handle_message.
    """
    # pick message content
    message = update.get("message") or update.get("edited_message") or update.get("channel_post") or {}
    if not message:
        # could be callback_query or other update type
        if "callback_query" in update:
            await handle_callback(update["callback_query"])
        return

    from_user = message.get("from", {})
    user_id = from_user.get("id")
    text = message.get("text", "") or ""
    chat_id = message.get("chat", {}).get("id")

    if not user_id or not chat_id:
        logger.warning("Received message without user/chat: %s", message)
        return

    ensure_user_record(user_id)

    # simple /start handling
    if text.startswith("/start"):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Free Video ▶️", callback_data="free_video")],
            [InlineKeyboardButton("Get Premium 💎", url=f"{DOMAIN}/buy")]  # sample link
        ])
        await send_message_safe(chat_id, f"Hello! Welcome to ANGEL. Free limit: {FREE_LIMIT} videos.", reply_markup=keyboard)
        return

    # fallback: text search could be a request for video name
    if text.strip():
        # naive search in videos collection
        try:
            cursor = videos.find({"title": {"$regex": text.strip(), "$options": "i"}}).limit(10)
            found = list(cursor)
        except PyMongoError:
            logger.exception("Error searching videos")
            found = []

        if not found:
            await send_message_safe(chat_id, "No videos found for your query.")
            return

        # send first video as sample with "Next" button
        first = found[0]
        buttons = []
        buttons.append([InlineKeyboardButton("Next ▶️", callback_data=f"next:0:{text.strip()}")])
        # also add ad/premium buttons under the content if needed
        buttons.append([InlineKeyboardButton("Watch Ad to Continue", callback_data="watch_ad")])
        markup = InlineKeyboardMarkup(buttons)
        # send a message with video caption (we assume stored file_id in DB)
        file_id = first.get("file_id")
        if file_id:
            try:
                await bot.send_video(chat_id=chat_id, video=file_id, caption=first.get("title", ""), reply_markup=markup)
            except TelegramError:
                # fall back to text message
                await send_message_safe(chat_id, f"{first.get('title')}\n\n(video send failed)", reply_markup=markup)
        else:
            await send_message_safe(chat_id, f"{first.get('title')}", reply_markup=markup)
        return

async def handle_callback(callback: dict):
    """
    Handle callback_query dict from update.
    This function is async because bot methods are async.
    """
    try:
        data = callback.get("data", "")
        from_user = callback.get("from", {})
        user_id = from_user.get("id")
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        ensure_user_record(user_id)

        if data == "free_video":
            # send a sample free video flow (increment free count)
            user = users.find_one({"user_id": user_id})
            free_watched = user.get("free_watched", 0) if user else 0
            if free_watched >= FREE_LIMIT:
                # prompt to watch ad or buy premium
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")],
                    [InlineKeyboardButton("Buy Premium", url=f"{DOMAIN}/buy")]
                ])
                await send_message_safe(chat_id, "Free limit reached. Watch ad or buy premium.", reply_markup=kb)
                return
            # otherwise send next free video (logic placeholder)
            users.update_one({"user_id": user_id}, {"$inc": {"free_watched": 1}})
            await send_message_safe(chat_id, f"Serving free video #{free_watched + 1}")
            return

        if data == "watch_ad":
            # create ad session and send shortener url (placeholder)
            token = f"ad-{user_id}-{int(datetime.utcnow().timestamp())}"
            create_ad_session(user_id, token, provider_response={})
            # construct short link or ad link (use DOMAIN or external provider)
            ad_url = f"{DOMAIN}/ad/redirect/{token}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open Ad Link", url=ad_url)]])
            await send_message_safe(chat_id, "Open this link, watch the ad and then return to the bot.", reply_markup=kb)
            return

        # handle 'next' pattern: next:index:query
        if data.startswith("next:"):
            _, idx_str, query = data.split(":", 2)
            try:
                idx = int(idx_str) + 1
            except ValueError:
                idx = 0
            # fetch query results and send idx-th video
            try:
                cursor = list(videos.find({"title": {"$regex": query, "$options": "i"}}).skip(idx).limit(1))
            except PyMongoError:
                cursor = []
            if not cursor:
                await send_message_safe(chat_id, "No more videos.")
                return
            item = cursor[0]
            buttons = [
                [InlineKeyboardButton("Next ▶️", callback_data=f"next:{idx}:{query}")],
                [InlineKeyboardButton("Watch Ad to continue", callback_data="watch_ad")]
            ]
            markup = InlineKeyboardMarkup(buttons)
            file_id = item.get("file_id")
            if file_id:
                try:
                    await bot.send_video(chat_id=chat_id, video=file_id, caption=item.get("title", ""), reply_markup=markup)
                except TelegramError:
                    await send_message_safe(chat_id, item.get("title", ""), reply_markup=markup)
            else:
                await send_message_safe(chat_id, item.get("title", ""), reply_markup=markup)
            return

    except Exception:
        logger.exception("Failed to handle callback")

# ---------- Entry exported to routes.py ----------
async def handle_update(raw_update: dict):
    """
    Entry point expected by routes.py
    Accept raw JSON update and forward to appropriate handler.
    """
    # Prioritize callback_query
    if "callback_query" in raw_update:
        await handle_callback(raw_update["callback_query"])
        return

    # else handle message-based updates
    await handle_message(raw_update)

# expose a few functions elsewhere if other modules import them
__all__ = [
    "handle_update",
    "ensure_user_record",
    "create_ad_session",
    "mark_ad_completed",
]e":
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
