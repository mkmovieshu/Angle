# app/telegram/handlers.py
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update
from telegram import Message

from app.telegram.bot import bot
from app.telegram.membership import is_user_member
from app.telegram.video_service import ensure_user_doc, send_one_video
from app.telegram.keyboards import join_group_buttons, video_control_buttons
from app.ads.service import create_ad_session
from app.database import users, videos, ad_sessions
from app.config import FREE_LIMIT, REQUIRED_GROUP_LINK, ADMIN_CHAT_ID

from app.telegram.channel_import import import_channel_post  # NEW

log = logging.getLogger("handlers")
log.setLevel(logging.INFO)


async def handle_update(raw_update: dict):
    """
    Main entry function used by routes.py when webhook posts an update.
    This will dispatch channel posts, messages, and callback queries.
    """
    try:
        upd = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Invalid update JSON: %s", e)
        return

    # Channel post -> import into DB
    if upd.channel_post:
        try:
            await import_channel_post(upd.channel_post)
        except Exception:
            log.exception("channel import failed")
        return

    # message -> user flow
    if upd.message:
        await handle_message(upd)
        return

    # callback queries handled elsewhere if present
    if upd.callback_query:
        await handle_callback(upd)
        return


# --- helper to get unseen video for user (delegated to video_service) ---
# send_one_video(user_id, user_doc, ad_token=None, ad_url=None)


async def handle_message(update: Update):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    user_id = user.id
    username = getattr(user, "username", None)

    # Ensure user doc exists
    u = await ensure_user_doc(user_id, username)

    text = (msg.text or "").strip()

    # Force join: if not a member, prompt join first
    if not await is_user_member(user_id):
        kb = join_group_buttons(REQUIRED_GROUP_LINK)
        await bot.send_message(user_id, "📌 ముందుగా మా గ్రూప్‌లో Join అవ్వాలి!\nJoin చేసి 'I Joined' నొక్కండి.", reply_markup=kb)
        return

    # /start handler: welcome message
    if text.startswith("/start"):
        await bot.send_message(user_id, f"👋 Welcome to ANGEL! You get {FREE_LIMIT} free videos. Send any message to receive one.")
        return

    # premium check
    premium_until = u.get("premium_until")
    if premium_until:
        try:
            pu = datetime.fromisoformat(premium_until) if isinstance(premium_until, str) else premium_until
            if pu and pu > datetime.utcnow():
                await send_one_video(user_id, u)
                return
        except Exception:
            log.exception("premium parse fail")

    # free quota
    used = u.get("free_used", 0)
    if used < FREE_LIMIT:
        success = await send_one_video(user_id, u)
        if success:
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> ad session
    token, short_url = await create_ad_session(user_id)
    if not short_url:
        await bot.send_message(user_id, "Sorry — ad provider temporarily unavailable. Try again later.")
        return

    # ensure still member before sending ad button
    if not await is_user_member(user_id):
        kb = join_group_buttons(REQUIRED_GROUP_LINK)
        await bot.send_message(user_id, "Join required group first to watch more videos.", reply_markup=kb)
        return

    await send_one_video(user_id, u, ad_token=token, ad_url=short_url)


async def handle_callback(update: Update):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    user_id = q.from_user.id
    await q.answer()

    # I Joined pressed
    if data == "check_join":
        if await is_user_member(user_id):
            u = await ensure_user_doc(user_id, getattr(q.from_user, "username", None))
            await q.message.reply_text("✅ Membership confirmed. Sending video now.")
            used = u.get("free_used", 0)
            if used < FREE_LIMIT:
                sent = await send_one_video(user_id, u)
                if sent:
                    await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
                return
            token, short_url = await create_ad_session(user_id)
            if not short_url:
                await q.message.reply_text("Ad provider failed. Try later.")
                return
            await send_one_video(user_id, u, ad_token=token, ad_url=short_url)
        else:
            kb = join_group_buttons(REQUIRED_GROUP_LINK)
            await q.message.reply_text("We still can't verify membership. Please join and press 'I Joined'.", reply_markup=kb)
        return

    # Next video
    if data == "next_video":
        u = await users.find_one({"user_id": user_id}) or await ensure_user_doc(user_id)
        used = u.get("free_used", 0)
        if used < FREE_LIMIT:
            sent = await send_one_video(user_id, u)
            if sent:
                await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
            return
        token, short_url = await create_ad_session(user_id)
        if not short_url:
            await q.message.reply_text("Ad provider unavailable. Try later.")
            return
        await send_one_video(user_id, u, ad_token=token, ad_url=short_url)
        return

    # Show free count
    if data == "show_free":
        u = await users.find_one({"user_id": user_id}) or await ensure_user_doc(user_id)
        used = u.get("free_used", 0)
        await q.message.reply_text(f"Used: {used}\nRemaining: {max(0, FREE_LIMIT - used)}")
        return

    # Premium menu
    if data == "premium_menu":
        await q.message.reply_text("Premium menu: contact admin to subscribe.")
        return

    # Ad check token
    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_sessions.find_one({"token": token})
        if rec and rec.get("status") == "completed":
            await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
            await q.message.reply_text("Ad verified — free count reset.")
        else:
            await q.answer("Not verified yet. Try again after finishing the ad.", show_alert=True)
        return
