# app/telegram/handlers.py
# Full, robust handlers for ANGEL bot
# - safe checks for provider responses
# - handles messages and callback_query
# - integrates ad-session create & verify
# - logs unexpected errors

import logging
from datetime import datetime
from typing import Optional, Any, Dict

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from app.telegram.bot import bot
from app.database import users, videos, ad_sessions
from app.ads.service import create_ad_session, mark_ad_completed
from app.telegram.keyboards import ad_buttons, free_or_premium
from app.config import DOMAIN, ADMIN_CHAT_ID

log = logging.getLogger("app.telegram.handlers")
log.setLevel(logging.INFO)

FREE_LIMIT = 5  # number of free videos per cycle

# ---------------- utility helpers ----------------

def _now_iso():
    return datetime.utcnow().isoformat()


async def _ensure_user_doc(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """Return user doc, create if missing."""
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
    """Send one video from videos collection (first found). Return True if sent."""
    vid = await videos.find_one({})
    if not vid or not isinstance(vid.get("file_id"), str):
        await bot.send_message(chat_id, "No videos available at the moment. Try later.")
        return False

    try:
        await bot.send_video(chat_id=chat_id, video=vid["file_id"], caption=vid.get("caption", ""))
        return True
    except TelegramError as e:
        log.exception("Failed to send video to %s: %s", chat_id, e)
        # notify user minimally
        try:
            await bot.send_message(chat_id, "Failed to deliver video. Try again later.")
        except Exception:
            pass
        return False


# ---------------- main entry used by webhook ----------------

async def handle_update(raw_update: dict):
    """
    Called from FastAPI webhook route.
    raw_update: raw JSON dict from Telegram.
    """
    try:
        update = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Failed to parse update JSON: %s", e)
        return

    try:
        # message (text, commands etc.)
        if update.message:
            await handle_message(update, None)

        # callback_query (inline buttons)
        if update.callback_query:
            await handle_callback(update, None)

    except Exception as e:
        # log everything and try to notify admin if possible
        log.exception("Unhandled error processing update: %s", e)
        try:
            if ADMIN_CHAT_ID:
                await bot.send_message(ADMIN_CHAT_ID, f"Handler error: {e}")
        except Exception:
            pass


# ---------------- message handler ----------------

async def handle_message(update: Update, context: Optional[ContextTypes.DEFAULT_TYPE]):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    user_id = user.id
    username = getattr(user, "username", None)

    # ensure user doc exists
    u = await _ensure_user_doc(user_id, username)

    # simple command handling
    text = (msg.text or "").strip()

    if text.startswith("/start"):
        await bot.send_message(user_id, f"👋 Welcome to ANGEL! You get {FREE_LIMIT} free videos. Send any message to receive one.")
        return

    # If user is premium (simple check), allow unlimited (basic placeholder)
    premium_until = u.get("premium_until")
    if premium_until:
        try:
            # if stored as ISO string
            if isinstance(premium_until, str):
                pu = datetime.fromisoformat(premium_until)
            elif isinstance(premium_until, datetime):
                pu = premium_until
            else:
                pu = None
            if pu and pu > datetime.utcnow():
                # premium user -> send video
                sent = await _send_video_if_available(user_id)
                if sent:
                    # optionally track sent_file_ids (not implemented here)
                    pass
                return
        except Exception:
            # ignore parse problems and continue with free flow
            log.exception("Failed to parse premium_until for user %s", user_id)

    # Free-flow: check count
    used = u.get("free_used", 0)
    if used < FREE_LIMIT:
        # send one and increment counter
        sent_ok = await _send_video_if_available(user_id)
        if sent_ok:
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> create ad session and show buttons
    token, short_url = await create_ad_session(user_id)
    # short_url may be None if provider failed
    if not short_url or not isinstance(short_url, str):
        # inform user gracefully and notify admin
        await bot.send_message(user_id, "Sorry — ad provider temporarily unavailable. Try again in a few moments.")
        log.warning("Ad session created but no short_url for token=%s user=%s provider_response stored", token, user_id)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Ad session failed: token={token} user={user_id}")
            except Exception:
                pass
        return

    # send ad buttons
    try:
        await bot.send_message(
            user_id,
            "You reached the free limit. Watch an ad to unlock more videos:",
            reply_markup=ad_buttons(short_url, token)
        )
    except TelegramError as e:
        log.exception("Failed to send ad buttons to %s: %s", user_id, e)
        # fallback: just send short_url as message
        try:
            await bot.send_message(user_id, f"Open this link to watch ad: {short_url}")
        except Exception:
            pass


# ---------------- callback handler ----------------

async def handle_callback(update: Update, context: Optional[ContextTypes.DEFAULT_TYPE]):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""
    user_id = q.from_user.id

    # Acknowledge the callback quickly if needed
    try:
        await q.answer()
    except Exception:
        pass

    # ad_check:<token>
    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_sessions.find_one({"token": token})
        if not rec:
            await q.answer("Ad session not found.", show_alert=True)
            return

        status = rec.get("status")
        if status == "completed":
            # reset free counter
            await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
            await q.message.reply_text("✅ Ad verified — your free videos are unlocked. Enjoy!")
            return

        # not yet completed: maybe provider redirect happened earlier or is delayed
        # try to be helpful: tell user to click the return-to-bot link in browser page
        await q.answer("Ad not verified yet. If you finished watching, click the 'Return to Bot' on the ad page and then press this button again.", show_alert=True)
        return

    # premium menu
    if data == "premium_menu":
        await q.message.reply_text("Premium Plans:\n\n10 Days – ₹100\n20 Days – ₹150\n30 Days – ₹200\n\nContact admin to purchase.", reply_markup=free_or_premium())
        return

    # fallback
    await q.answer()
