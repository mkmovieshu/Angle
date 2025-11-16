# app/telegram/handlers.py

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from telegram import Update, Message
from telegram.error import TelegramError

from app.telegram.bot import bot
from app.database import users, videos, ad_sessions
from app.ads.service import create_ad_session
from app.telegram.keyboards import video_control_buttons
from app.config import ADMIN_CHAT_ID

log = logging.getLogger("handlers")
log.setLevel(logging.INFO)

FREE_LIMIT = 5


def _now():
    return datetime.utcnow().isoformat()


async def _ensure_user(user_id: int, username: Optional[str] = None):
    u = await users.find_one({"user_id": user_id})
    if u:
        if "sent_file_ids" not in u:
            await users.update_one({"user_id": user_id}, {"$set": {"sent_file_ids": []}})
            u["sent_file_ids"] = []
        return u

    doc = {
        "user_id": user_id,
        "username": username,
        "free_used": 0,
        "premium_until": None,
        "sent_file_ids": [],
        "created_at": _now()
    }

    await users.insert_one(doc)
    return doc


async def _pick_unseen_video(u):
    sent = u.get("sent_file_ids", [])

    all_videos = []
    async for v in videos.find({}, sort=[("created_at", 1)]):
        all_videos.append(v)

    for v in all_videos:
        fid = v.get("file_id")
        if fid and fid not in sent:
            return v

    return None


async def _record_sent(user_id, file_id):
    await users.update_one({"user_id": user_id}, {"$addToSet": {"sent_file_ids": file_id}})


async def handle_channel_post(msg: Message):
    try:
        file_id = None
        media = None

        if msg.video:
            file_id = msg.video.file_id
            media = "video"
        elif msg.document:
            file_id = msg.document.file_id
            media = "document"
        elif msg.animation:
            file_id = msg.animation.file_id
            media = "animation"

        if not file_id:
            return

        exist = await videos.find_one({"file_id": file_id})
        if exist:
            return

        doc = {
            "file_id": file_id,
            "type": media,
            "caption": msg.caption or "",
            "created_at": _now()
        }

        await videos.insert_one(doc)

        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Imported video {file_id}")
            except:
                pass

    except Exception as e:
        log.exception("handle_channel_post error: %s", e)


async def handle_update(raw):
    try:
        update = Update.de_json(raw, bot)
    except Exception:
        return

    if update.channel_post:
        await handle_channel_post(update.channel_post)
        return

    if update.message:
        await handle_message(update)
        return

    if update.callback_query:
        await handle_callback(update)
        return


async def _send_video(chat_id, u, ad_token=None, ad_url=None):
    vid = await _pick_unseen_video(u)
    if not vid:
        await bot.send_message(chat_id, "No more videos available.")
        return False

    file_id = vid["file_id"]
    caption = vid.get("caption", "")

    kb = video_control_buttons(ad_token, ad_url)

    try:
        await bot.send_video(chat_id, file_id, caption=caption, reply_markup=kb)
        await _record_sent(u["user_id"], file_id)
        return True
    except TelegramError as e:
        log.exception("send_video error: %s", e)
        return False


async def handle_message(update: Update):
    msg = update.message
    user = msg.from_user
    user_id = user.id

    u = await _ensure_user(user_id, user.username)

    if msg.text and msg.text.startswith("/start"):
        await bot.send_message(user_id, "Welcome! Send any message for video.")
        return

    premium = u.get("premium_until")
    if premium:
        try:
            p = datetime.fromisoformat(premium)
            if p > datetime.utcnow():
                # premium active
                await _send_video(user_id, u)
                return
        except:
            pass

    used = u.get("free_used", 0)
    if used < FREE_LIMIT:
        if await _send_video(user_id, u):
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free over → need ad
    token, url = await create_ad_session(user_id)
    if not url:
        await bot.send_message(user_id, "Ad provider offline, try later.")
        return

    await _send_video(user_id, u, ad_token=token, ad_url=url)


async def handle_callback(update: Update):
    q = update.callback_query
    data = q.data
    user_id = q.from_user.id

    await q.answer()

    if data == "next_video":
        u = await users.find_one({"user_id": user_id}) or await _ensure_user(user_id)
        used = u.get("free_used", 0)

        if used < FREE_LIMIT:
            if await _send_video(user_id, u):
                await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
            return

        token, url = await create_ad_session(user_id)
        await _send_video(user_id, u, ad_token=token, ad_url=url)
        return

    if data == "show_free":
        u = await users.find_one({"user_id": user_id})
        used = u.get("free_used", 0)
        rem = max(0, FREE_LIMIT - used)
        await q.message.reply_text(f"Used: {used}\nRemaining: {rem}")
        return

    if data == "premium_menu":
        await q.message.reply_text(
            "Premium:\n10 days ₹100\n20 days ₹150\n30 days ₹200\nContact admin."
        )
        return

    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_sessions.find_one({"token": token})
        if rec and rec.get("status") == "completed":
            await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
            await q.message.reply_text("Ad verified! Free videos restored.")
        else:
            await q.answer("Not verified yet. Try again.", show_alert=True)
