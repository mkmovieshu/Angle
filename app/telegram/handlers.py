import logging
from datetime import datetime
from pymongo import MongoClient
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.telegram.bot import bot
from app.config import MONGO_URI, FREE_LIMIT, DOMAIN

logger = logging.getLogger("uvicorn.error")

# -----------------------------
# Mongo Setup (fixed)
# -----------------------------
client = MongoClient(MONGO_URI)

try:
    default_db = client.get_default_database()
except Exception as e:
    logger.warning("get_default_database() failed, using fallback DB")
    default_db = None

db = default_db if default_db is not None else client["video_web_bot"]

users = db.users
videos = db.videos
ad_sessions = db.ad_sessions


# -----------------------------
# DB Helpers
# -----------------------------
def ensure_user(user_id: int):
    u = users.find_one({"user_id": user_id})
    if not u:
        users.insert_one({
            "user_id": user_id,
            "free_watched": 0,
            "premium": False,
            "created_at": datetime.utcnow(),
        })
    return users.find_one({"user_id": user_id})


def create_ad_session(user_id: int):
    token = f"{user_id}-{int(datetime.utcnow().timestamp())}"
    ad_sessions.insert_one({
        "user_id": user_id,
        "token": token,
        "completed": False,
        "created_at": datetime.utcnow()
    })
    return token


def mark_ad_completed(token: str):
    return ad_sessions.find_one_and_update(
        {"token": token},
        {"$set": {"completed": True}},
        return_document=True
    )


# -----------------------------
# Messaging Helpers
# -----------------------------
async def send(chat_id, text, kb=None):
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except TelegramError:
        logger.exception("Send message failed")


# -----------------------------
# Callback Handler
# -----------------------------
async def handle_callback(q):
    data = q.get("data", "")
    user_id = q["from"]["id"]
    chat_id = q["message"]["chat"]["id"]

    user = ensure_user(user_id)

    # ------------------------
    # FREE VIDEO REQUEST
    # ------------------------
    if data == "free_video":
        if user["free_watched"] >= FREE_LIMIT:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")],
                [InlineKeyboardButton("Buy Premium", url=f"{DOMAIN}/buy")]
            ])
            await send(chat_id, "Free limit reached! Watch Ad to continue.", kb)
            return

        users.update_one({"user_id": user_id}, {"$inc": {"free_watched": 1}})
        await send(chat_id, f"Here is your free video #{user['free_watched'] + 1}")
        return

    # ------------------------
    # AD START
    # ------------------------
    if data == "watch_ad":
        token = create_ad_session(user_id)
        ad_url = f"{DOMAIN}/ad/{token}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Open Ad", url=ad_url)],
            [InlineKeyboardButton("I Watched Ad", callback_data=f"ad_done:{token}")]
        ])
        await send(chat_id, "Watch this ad fully and then click below:", kb)
        return

    # ------------------------
    # AD FINISHED
    # ------------------------
    if data.startswith("ad_done:"):
        token = data.split(":")[1]
        s = ad_sessions.find_one({"token": token})

        if not s or not s.get("completed"):
            await send(chat_id, "You didn’t finish the ad. Watch fully!")
            return

        await send(chat_id, "Ad verified! You can continue watching videos.")
        return

    # ------------------------
    # NEXT: index:query
    # ------------------------
    if data.startswith("next:"):
        _, index, query = data.split(":", 2)
        index = int(index) + 1

        result = list(videos.find({"title": {"$regex": query, "$options": "i"}}).skip(index).limit(1))
        if not result:
            await send(chat_id, "No more videos.")
            return

        vid = result[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"next:{index}:{query}")],
            [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")]
        ])

        try:
            await bot.send_video(chat_id, vid["file_id"], caption=vid["title"], reply_markup=kb)
        except:
            await send(chat_id, vid["title"], kb)

        return


# -----------------------------
# Message Handler
# -----------------------------
async def handle_message(update):
    msg = update.get("message", {})
    text = msg.get("text", "")
    user_id = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")

    if not user_id:
        return

    ensure_user(user_id)

    if text.startswith("/start"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Free Video ▶", callback_data="free_video")],
            [InlineKeyboardButton("Buy Premium 💎", url=f"{DOMAIN}/buy")]
        ])
        await send(chat_id, f"Welcome! Free limit: {FREE_LIMIT}", kb)
        return

    # SEARCH
    if text.strip():
        result = list(videos.find({"title": {"$regex": text, "$options": "i"}}).limit(1))
        if not result:
            await send(chat_id, "No results.")
            return

        vid = result[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"next:0:{text}")],
            [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")]
        ])

        try:
            await bot.send_video(chat_id, vid["file_id"], caption=vid["title"], reply_markup=kb)
        except:
            await send(chat_id, vid["title"], kb)


# -----------------------------
# MAIN ENTRY (used by routes.py)
# -----------------------------
async def handle_update(update):
    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return

    await handle_message(update)a clickable URL
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
