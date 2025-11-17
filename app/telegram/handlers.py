import logging
from datetime import datetime
from pymongo import MongoClient
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.telegram.bot import bot
from app.config import MONGO_URL, FREE_LIMIT, DOMAIN

logger = logging.getLogger("uvicorn.error")

# -----------------------------
# MongoDB setup
# -----------------------------
client = MongoClient(MONGO_URL)

try:
    default_db = client.get_default_database()
except Exception:
    default_db = None

db = default_db if default_db is not None else client["video_web_bot"]

users = db.users
videos = db.videos
ad_sessions = db.ad_sessions

# -----------------------------
# DB helpers
# -----------------------------
def ensure_user(user_id: int):
    """Ensure user doc exists; return it."""
    u = users.find_one({"user_id": user_id})
    if not u:
        users.insert_one({
            "user_id": user_id,
            "free_watched": 0,
            "premium": False,
            "created_at": datetime.utcnow(),
        })
        u = users.find_one({"user_id": user_id})
    return u


def create_ad_session(user_id: int):
    """Create an ad session token and store it."""
    token = f"{user_id}-{int(datetime.utcnow().timestamp())}"
    ad_sessions.insert_one({
        "user_id": user_id,
        "token": token,
        "completed": False,
        "created_at": datetime.utcnow()
    })
    return token


def mark_ad_completed(token: str):
    """Mark ad session completed. Returns updated doc or None."""
    return ad_sessions.find_one_and_update(
        {"token": token},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}},
        return_document=True
    )


# -----------------------------
# Messaging helpers
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
        logger.exception("send() failed for chat_id=%s", chat_id)


# -----------------------------
# Callback handling
# -----------------------------
async def handle_callback(q):
    """
    callback_query payload expected shape:
    {
      "id": "...",
      "from": {...},
      "message": {...},
      "data": "..."
    }
    """
    data = q.get("data", "")
    user_id = q["from"]["id"]
    chat_id = q["message"]["chat"]["id"]

    ensure_user(user_id)

    # free video request
    if data == "free_video":
        u = users.find_one({"user_id": user_id})
        if u.get("premium"):
            # premium users: unlimited
            await send(chat_id, "You are premium — sending a video...")
            # send first matching video (example)
            v = videos.find_one({})
            if v:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Next ▶", callback_data=f"next:0:all")],
                ])
                try:
                    await bot.send_video(chat_id, v["file_id"], caption=v.get("title", ""), reply_markup=kb)
                except TelegramError:
                    await send(chat_id, v.get("title", "Video"), kb)
            else:
                await send(chat_id, "No videos in bin channel.")
            return

        # non-premium: check free count
        u = users.find_one({"user_id": user_id})
        free_watched = u.get("free_watched", 0)
        if free_watched >= FREE_LIMIT:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")],
                [InlineKeyboardButton("Buy Premium 💎", url=f"{DOMAIN}/buy")]
            ])
            await send(chat_id, "Free limit reached. Watch an ad or buy premium.", kb)
            return

        # increment and send a video
        users.update_one({"user_id": user_id}, {"$inc": {"free_watched": 1}})
        v = videos.find_one({})
        if not v:
            await send(chat_id, "No videos available.")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"next:0:all")],
            [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")]
        ])
        try:
            await bot.send_video(chat_id, v["file_id"], caption=v.get("title", ""), reply_markup=kb)
        except TelegramError:
            await send(chat_id, v.get("title", "Video"), kb)
        return

    # watch ad: create ad session and give short link/button
    if data == "watch_ad":
        token = create_ad_session(user_id)
        ad_url = f"{DOMAIN}/ad/{token}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Open Ad", url=ad_url)],
            [InlineKeyboardButton("I Watched Ad", callback_data=f"ad_done:{token}")]
        ])
        await send(chat_id, "Open the ad, watch fully, then press 'I Watched Ad'.", kb)
        return

    # user clicked 'I Watched Ad' - verify session
    if data.startswith("ad_done:"):
        token = data.split(":", 1)[1]
        sess = ad_sessions.find_one({"token": token})
        if not sess:
            await send(chat_id, "Ad session not found. Please open the ad first.")
            return

        # If the external ad verification updates this session.completed=True,
        # we require that to be true here. If your ad provider returns a callback
        # to your webserver to mark it completed, this check will pass.
        if not sess.get("completed"):
            await send(chat_id, "Ad not verified yet. Make sure you watched the ad and returned to the bot.")
            return

        # mark complete again just in case and allow the user to continue
        mark_ad_completed(token)
        # reset free_watched so user can continue (adjust logic as needed)
        users.update_one({"user_id": user_id}, {"$set": {"free_watched": 0}})
        await send(chat_id, "Ad verified — you can continue watching free videos.")
        return

    # pagination/next handler: data format "next:{index}:{query}"
    if data.startswith("next:"):
        try:
            _, index_s, query = data.split(":", 2)
            index = int(index_s)
        except Exception:
            await send(chat_id, "Invalid next request.")
            return

        # select next video based on query; 'all' returns from start+index
        if query == "all":
            cursor = videos.find({}).skip(index).limit(1)
        else:
            cursor = videos.find({"title": {"$regex": query, "$options": "i"}}).skip(index).limit(1)

        result = list(cursor)
        if not result:
            await send(chat_id, "No more videos.")
            return

        vid = result[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"next:{index+1}:{query}")],
            [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")]
        ])
        try:
            await bot.send_video(chat_id, vid["file_id"], caption=vid.get("title", ""), reply_markup=kb)
        except TelegramError:
            await send(chat_id, vid.get("title", "Video"), kb)
        return


# -----------------------------
# Message handling
# -----------------------------
async def handle_message(update):
    """
    update = {"message": {...}} expected.
    """
    msg = update.get("message", {}) or {}
    text = msg.get("text", "") or ""
    from_user = msg.get("from", {}) or {}
    user_id = from_user.get("id")
    chat = msg.get("chat", {}) or {}
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return

    ensure_user(user_id)

    # /start
    if text.startswith("/start"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Free Video ▶", callback_data="free_video")],
            [InlineKeyboardButton("Buy Premium 💎", url=f"{DOMAIN}/buy")]
        ])
        await send(chat_id, f"Welcome — free limit: {FREE_LIMIT}.", kb)
        return

    # any text -> treat as search query (first result)
    q = text.strip()
    if q:
        result = list(videos.find({"title": {"$regex": q, "$options": "i"}}).limit(1))
        if not result:
            await send(chat_id, "No results found.")
            return

        vid = result[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Next ▶", callback_data=f"next:0:{q}")],
            [InlineKeyboardButton("Watch Ad", callback_data="watch_ad")]
        ])
        try:
            await bot.send_video(chat_id, vid["file_id"], caption=vid.get("title", ""), reply_markup=kb)
        except TelegramError:
            await send(chat_id, vid.get("title", "Video"), kb)


# -----------------------------
# Top-level entry used by routes.py
# -----------------------------
async def handle_update(update):
    # update may contain "callback_query" or "message"
    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return

    if "message" in update:
        await handle_message(update)
        return

    # unknown update - ignore
    logger.debug("Unhandled update type: %s", update.keys())
# handlers.py add near top imports
from app.telegram.bin_importer import run_import

# మరియు ఎక్కడైనా admin-only command లేదా startup hook లో
# ఉదాహరణ: ఈ ఫంక్షన్ admin request తో కలుసుకో
async def admin_import_bin(update, context):
    # only allow admin
    inserted = run_import(limit=200)
    await bot.send_message(ADMIN_CHAT_ID, f"Imported {inserted} videos from BIN channel.")
