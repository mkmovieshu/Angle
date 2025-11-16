# app/telegram/handlers.py
# ANGEL handlers with channel_post import support
# Replace your existing handlers.py with this file.

import logging
from datetime import datetime
from typing import Optional, Any, Dict

from telegram import Update, Message
from telegram.error import TelegramError

from app.telegram.bot import bot
from app.database import users, videos, ad_sessions
from app.ads.service import create_ad_session
from app.telegram.keyboards import ad_buttons, free_or_premium
from app.config import ADMIN_CHAT_ID

log = logging.getLogger("app.telegram.handlers")
log.setLevel(logging.INFO)

FREE_LIMIT = 5  # number of free videos per cycle


def _now_iso():
    return datetime.utcnow().isoformat()


async def _ensure_user_doc(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    u = await users.find_one({"user_id": user_id})
    if u:
        return u
    doc = {
        "user_id": user_id,
        "username": username,
        "free_used": 0,
        "created_at": _now_iso(),
        "premium_until": None,
        "sent_file_ids": [],
    }
    await users.insert_one(doc)
    return doc


async def _send_video_if_available(chat_id: int) -> bool:
    vid = await videos.find_one({})
    if not vid or not isinstance(vid.get("file_id"), str):
        try:
            await bot.send_message(chat_id, "No videos available at the moment. Try later.")
        except Exception:
            pass
        return False
    try:
        await bot.send_video(chat_id=chat_id, video=vid["file_id"], caption=vid.get("caption", ""))
        return True
    except TelegramError as e:
        log.exception("Failed to send video to %s: %s", chat_id, e)
        try:
            await bot.send_message(chat_id, "Failed to deliver video. Try again later.")
        except Exception:
            pass
        return False


# ---------------- channel_post handler ----------------
async def handle_channel_post(msg: Message):
    """
    Called when the bot receives update.channel_post.
    If the post contains a video/document with video, save file_id into videos collection.
    """
    try:
        chat = msg.chat
        chat_id = chat.id
        # detect media types that can be treated as videos
        file_id = None
        media_type = None

        if msg.video:
            file_id = msg.video.file_id
            media_type = "video"
        elif msg.document:
            # document may be a video file (mp4) or other; best-effort check mime type in document.file_name
            file_id = msg.document.file_id
            media_type = "document"
        elif msg.animation:
            # gif/animation — treat as video if desired
            file_id = msg.animation.file_id
            media_type = "animation"
        elif msg.video_note:
            file_id = msg.video_note.file_id
            media_type = "video_note"

        if not file_id:
            # nothing to do
            return

        doc = {
            "file_id": file_id,
            "type": media_type,
            "caption": msg.caption or "",
            "from_channel_id": chat_id,
            "channel_post_id": msg.message_id,
            "created_at": _now_iso()
        }

        # Avoid duplicates: simple check by file_id or by channel_post_id
        exists = await videos.find_one({"$or": [{"file_id": file_id}, {"channel_post_id": msg.message_id}]})
        if exists:
            log.info("Channel post already stored file_id=%s post=%s", file_id, msg.message_id)
            return

        await videos.insert_one(doc)
        log.info("Imported channel video file_id=%s from channel %s", file_id, chat_id)

        # optional: notify admin that new video saved
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Imported video from channel {chat.title or chat_id}: file_id={file_id}")
            except Exception:
                pass

    except Exception as e:
        log.exception("Error in handle_channel_post: %s", e)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Error importing channel post: {e}")
            except Exception:
                pass


# ---------------- main webhook entry ----------------
async def handle_update(raw_update: dict):
    """
    Called from FastAPI webhook route with raw JSON update.
    """
    try:
        update = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Failed to parse update JSON: %s", e)
        return

    try:
        # channel_post (messages posted in channels where bot is admin)
        if update.channel_post:
            await handle_channel_post(update.channel_post)
            return

        # regular user message
        if update.message:
            await handle_message(update)
            return

        # callback_query
        if update.callback_query:
            await handle_callback(update)
            return

    except Exception as e:
        log.exception("Unhandled error in handle_update: %s", e)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Handler error: {e}")
            except Exception:
                pass


# ---------------- message handler ----------------
async def handle_message(update: Update):
    msg = update.message
    if not msg:
        return
    user = msg.from_user
    user_id = user.id
    username = getattr(user, "username", None)

    # ensure user doc exists
    u = await _ensure_user_doc(user_id, username)

    text = (msg.text or "").strip()

    if text.startswith("/start"):
        await bot.send_message(user_id, f"👋 Welcome to ANGEL! You get {FREE_LIMIT} free videos. Send any message to receive one.")
        return

    # premium check (simple)
    premium_until = u.get("premium_until")
    if premium_until:
        try:
            if isinstance(premium_until, str):
                pu = datetime.fromisoformat(premium_until)
            elif isinstance(premium_until, datetime):
                pu = premium_until
            else:
                pu = None
            if pu and pu > datetime.utcnow():
                sent = await _send_video_if_available(user_id)
                return
        except Exception:
            log.exception("Failed to parse premium_until for user %s", user_id)

    used = u.get("free_used", 0)
    if used < FREE_LIMIT:
        sent_ok = await _send_video_if_available(user_id)
        if sent_ok:
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> create ad session
    token, short_url = await create_ad_session(user_id)
    if not short_url:
        await bot.send_message(user_id, "Sorry — ad provider temporarily unavailable. Try again in a few moments.")
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Ad session failed: token={token} user={user_id}")
            except Exception:
                pass
        return

    try:
        await bot.send_message(
            user_id,
            "You reached the free limit. Watch an ad to unlock more videos:",
            reply_markup=ad_buttons(short_url, token)
        )
    except TelegramError as e:
        log.exception("Failed to send ad buttons to %s: %s", user_id, e)
        try:
            await bot.send_message(user_id, f"Open this link to watch ad: {short_url}")
        except Exception:
            pass


# ---------------- callback handler ----------------
async def handle_callback(update: Update):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""
    user_id = q.from_user.id

    try:
        await q.answer()
    except Exception:
        pass

    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_sessions.find_one({"token": token})
        if not rec:
            await q.answer("Ad session not found.", show_alert=True)
            return

        status = rec.get("status")
        if status == "completed":
            await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
            await q.message.reply_text("✅ Ad verified — your free videos are unlocked. Enjoy!")
            return

        await q.answer("Ad not verified yet. Click 'Return to Bot' on the ad page then press this button again.", show_alert=True)
        return

    if data == "premium_menu":
        await q.message.reply_text("Premium Plans:\n\n10 Days – ₹100\n20 Days – ₹150\n30 Days – ₹200\n\nContact admin to purchase.", reply_markup=free_or_premium())
        return

    await q.answer()
