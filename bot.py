# bot.py
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_bot_db")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
BIN_CHANNEL = os.getenv("BIN_CHANNEL")  # channel where videos are stored (optional)
AD_CREATE_API = os.getenv("AD_CREATE_API", "https://yourdomain.com/ad/create")
FREE_BATCH = int(os.getenv("FREE_BATCH", "5"))
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", "0.35"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Mongo
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo[DB_NAME]
users_col = db["users"]
videos_col = db["videos"]
ad_col = db["ad_sessions"]

# Helpers
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def now():
    return datetime.utcnow()

# Keyboards
def start_keyboard():
    kb = [
        [InlineKeyboardButton("Free Video 🎁", callback_data="free_video")],
        [InlineKeyboardButton("Subscribe (premium)", callback_data="subscribe")],
        [InlineKeyboardButton("Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

# User ensure
async def ensure_user(user_id: int, username: Optional[str]):
    user = await users_col.find_one({"user_id": user_id})
    if user:
        if username and user.get("username") != username:
            await users_col.update_one({"user_id": user_id}, {"$set": {"username": username}})
        return user
    doc = {
        "user_id": user_id,
        "username": username,
        "premium_until": None,
        "video_index": 0,
        "free_used_in_cycle": 0,
        "cycle": 0,
        "created_at": now(),
    }
    await users_col.insert_one(doc)
    return doc

async def is_premium(user_doc) -> bool:
    pu = user_doc.get("premium_until")
    if not pu:
        return False
    if isinstance(pu, str):
        try:
            pu = datetime.fromisoformat(pu)
        except Exception:
            return False
    return pu > now()

# Bot Handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username)
    await update.message.reply_text(
        "Welcome. Get 5 free videos to start. Subscribe for unlimited access.",
        reply_markup=start_keyboard()
    )

async def import_video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin-only: forward a channel post or send a video to import
    user = update.effective_user
    if not is_admin(user.id):
        return
    msg = update.message
    video = msg.video or msg.document
    if not video:
        await msg.reply_text("Send/forward a message that contains a video file/document.")
        return
    doc = {
        "file_id": video.file_id,
        "caption": msg.caption or "",
        "uploader": user.id,
        "created_at": now()
    }
    res = await videos_col.insert_one(doc)
    await msg.reply_text(f"Imported video id={res.inserted_id}")

async def list_videos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Unauthorized.")
        return
    cursor = videos_col.find().sort("created_at", -1).limit(100)
    lines = []
    async for v in cursor:
        lines.append(f"{v.get('_id')} — {v.get('caption','')[:40]}")
    if not lines:
        await update.message.reply_text("No videos.")
    else:
        await update.message.reply_text("Videos:\n" + "\n".join(lines))

async def grant_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /grant_premium <user_id> <days>")
        return
    target = int(args[0])
    days = int(args[1])
    until = now() + timedelta(days=days)
    await users_col.update_one({"user_id": target}, {"$set": {"premium_until": until.isoformat()}}, upsert=True)
    await update.message.reply_text(f"Granted premium to {target} until {until.isoformat()}")

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /broadcast <video_id> <chat_id1> <chat_id2> ...")
        return
    video_id = args[0]
    targets = args[1:]
    from bson import ObjectId
    try:
        vdoc = await videos_col.find_one({"_id": ObjectId(video_id)})
    except Exception:
        await update.message.reply_text("Invalid video id.")
        return
    if not vdoc:
        await update.message.reply_text("Video not found.")
        return
    sent = 0
    failed = 0
    for t in targets:
        try:
            tid = int(t) if (t.lstrip('-').isdigit()) else t
            await context.bot.send_video(chat_id=tid, video=vdoc["file_id"], caption=vdoc.get("caption",""))
            sent += 1
        except Exception as e:
            log.exception("broadcast error")
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)
    await update.message.reply_text(f"Broadcast complete. sent={sent}, failed={failed}")

# Callback query handler
async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    udoc = await ensure_user(user.id, user.username)
    premium = await is_premium(udoc)

    if data == "help":
        await query.edit_message_text("Help:\nFree 5 videos, then watch ad to unlock next 5. Subscribe for unlimited.")
        return
    if data == "subscribe":
        await query.edit_message_text("To subscribe: contact admin or use /grant_premium (admin only).")
        return
    if data == "free_video":
        if premium:
            await send_next_video_for_user(user.id, query, context, udoc, premium=True)
            return
        if udoc.get("free_used_in_cycle", 0) < FREE_BATCH:
            await send_next_video_for_user(user.id, query, context, udoc, premium=False)
            return
        else:
            # create ad session via API
            async with aiohttp.ClientSession() as session:
                payload = {"user_id": user.id}
                try:
                    async with session.post(AD_CREATE_API, json=payload, timeout=10) as r:
                        if r.status == 201:
                            data = await r.json()
                            redirect = data.get("redirect_url")
                            # show watch ad keyboard
                            kb = [[InlineKeyboardButton("Open Short Ad 🔗", url=redirect)], [InlineKeyboardButton("I watched the ad ✅", callback_data=f"ad_check:{data.get('token')}")]]
                            await query.edit_message_text("You used your free batch. Watch short ad to unlock next.", reply_markup=InlineKeyboardMarkup(kb))
                            return
                except Exception:
                    log.exception("ad create failed")
            await query.edit_message_text("Failed to create ad session. Try again later.")
            return
    if data and data.startswith("ad_check:"):
        token = data.split(":",1)[1]
        # check status via /ad/status API
        ad_status_api = os.getenv("AD_STATUS_API", "https://yourdomain.com/ad/status/")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(ad_status_api + token, timeout=10) as r:
                    if r.status == 200:
                        js = await r.json()
                        if js.get("status") == "completed":
                            # unlock
                            await users_col.update_one({"user_id": user.id}, {"$set": {"free_used_in_cycle": 0}, "$inc": {"cycle": 1}})
                            await query.edit_message_text("Ad verified — unlocked next free batch. Press Free Video.")
                            return
                        else:
                            await query.edit_message_text("Ad not verified yet. Wait a few seconds and press the button again.")
                            return
            except Exception:
                log.exception("ad status check failed")
        await query.edit_message_text("Could not verify ad. Try again later.")

async def send_next_video_for_user(user_id: int, query, context, udoc, premium: bool):
    # efficient fetch: find one video at offset video_index
    idx = udoc.get("video_index", 0)
    vdoc = await videos_col.find().sort("created_at", 1).skip(idx).limit(1).to_list(length=1)
    if not vdoc:
        await query.edit_message_text("No videos available yet. Admin must import.")
        return
    vdoc = vdoc[0]
    try:
        await context.bot.send_video(chat_id=user_id, video=vdoc["file_id"], caption=vdoc.get("caption",""))
    except Exception as e:
        log.exception("send video error")
        await query.edit_message_text(f"Failed to send video: {e}")
        return
    update_ops = {"$inc": {"video_index": 1}}
    if not premium:
        update_ops["$inc"]["free_used_in_cycle"] = 1
    await users_col.update_one({"user_id": user_id}, update_ops)
    new_udoc = await users_col.find_one({"user_id": user_id})
    if await is_premium(new_udoc):
        await context.bot.send_message(chat_id=user_id, text="Premium: play next or browse.", reply_markup=start_keyboard())
        return
    if new_udoc.get("free_used_in_cycle", 0) < FREE_BATCH:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Next Free Video ▶️", callback_data="free_video")]])
        await context.bot.send_message(chat_id=user_id, text=f"Free videos used: {new_udoc.get('free_used_in_cycle')} / {FREE_BATCH}", reply_markup=kb)
    else:
        # show ad prompt
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(AD_CREATE_API, json={"user_id": user_id}, timeout=10) as r:
                    if r.status == 201:
                        data = await r.json()
                        redirect = data.get("redirect_url")
                        kb = [[InlineKeyboardButton("Open Short Ad 🔗", url=redirect)], [InlineKeyboardButton("I watched the ad ✅", callback_data=f"ad_check:{data.get('token')}")]]
                        await context.bot.send_message(chat_id=user_id, text=f"You've used {FREE_BATCH} free videos. Watch a short ad to unlock more.", reply_markup=InlineKeyboardMarkup(kb))
                        return
            except Exception:
                log.exception("ad create on post-send failed")
        await context.bot.send_message(chat_id=user_id, text="Please visit the bot menu to unlock more videos.")

# Message handler to import forwarded videos (admin)
async def forwarded_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    # only admin can import
    if not is_admin(user.id):
        return
    video = msg.video or msg.document
    if not video:
        return
    doc = {
        "file_id": video.file_id,
        "caption": msg.caption or "",
        "uploader": user.id,
        "created_at": now()
    }
    res = await videos_col.insert_one(doc)
    await msg.reply_text(f"Imported video {res.inserted_id}")

# Main
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("import", import_video_handler))
    app.add_handler(CommandHandler("list_videos", list_videos_handler))
    app.add_handler(CommandHandler("grant_premium", grant_premium))
    app.add_handler(CommandHandler("broadcast", broadcast_handler))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.ALL & filters.FORWARDED, forwarded_handler))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, forwarded_handler))
    return app

if __name__ == "__main__":
    app = build_app()
    log.info("Starting bot...")
    app.run_polling()
