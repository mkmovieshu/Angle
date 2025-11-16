# app/telegram/handlers.py
import logging
from datetime import datetime
from typing import Optional
from telegram import Update, Message
from app.telegram.bot import bot
from app.database import users, ad_sessions
from app.ads.service import create_ad_session
from app.telegram.video_service import ensure_user_doc, send_one_video
from app.telegram.membership import is_user_member
from app.telegram.keyboards import join_group_buttons
from app.config import FREE_LIMIT, REQUIRED_GROUP_INVITE, ADMIN_CHAT_ID

log = logging.getLogger("handlers_small")
log.setLevel(logging.INFO)

async def handle_channel_post(msg: Message):
    # keep existing import logic elsewhere (this file focuses on user flows)
    # if you still want channel imports here, reuse earlier code
    return

async def handle_update(raw_update: dict):
    try:
        update = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("parse update failed: %s", e)
        return

    if update.channel_post:
        # optional: import logic lives elsewhere
        return

    if update.message:
        await handle_message(update)
        return

    if update.callback_query:
        await handle_callback(update)
        return

async def handle_message(update: Update):
    msg = update.message
    if not msg:
        return
    user = msg.from_user
    uid = user.id
    username = getattr(user, "username", None)
    udoc = await ensure_user_doc(uid, username)

    text = (msg.text or "").strip()
    if text.startswith("/start"):
        # force-join prompt if needed
        if not await is_user_member(uid):
            kb = join_group_buttons(REQUIRED_GROUP_INVITE)
            await bot.send_message(uid, "Please join our group to access videos.", reply_markup=kb)
            return
        await bot.send_message(uid, f"Welcome — you have {FREE_LIMIT} free videos.")
        return

    # premium check
    premium_until = udoc.get("premium_until")
    if premium_until:
        try:
            pu = datetime.fromisoformat(premium_until) if isinstance(premium_until, str) else premium_until
            if pu and pu > datetime.utcnow():
                await send_one_video(uid, udoc)
                return
        except Exception:
            log.exception("premium parse failed")

    # free flow
    used = udoc.get("free_used", 0)
    if used < FREE_LIMIT:
        sent = await send_one_video(uid, udoc)
        if sent:
            await users.update_one({"user_id": uid}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> create ad session
    token, short_url = await create_ad_session(uid)
    if not short_url:
        await bot.send_message(uid, "Ad provider unavailable. Try later.")
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Ad creation failed for user {uid}")
            except Exception:
                pass
        return

    # Before sending, ensure membership
    if not await is_user_member(uid):
        kb = join_group_buttons(REQUIRED_GROUP_INVITE)
        await bot.send_message(uid, "Join the required group first to watch more videos.", reply_markup=kb)
        return

    # send one video with ad buttons
    await send_one_video(uid, udoc, ad_token=token, ad_url=short_url)

async def handle_callback(update: Update):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data or ""
    uid = q.from_user.id

    if data == "check_join":
        if await is_user_member(uid):
            udoc = await ensure_user_doc(uid, getattr(q.from_user, "username", None))
            await q.message.reply_text("Membership confirmed — sending video now.")
            used = udoc.get("free_used", 0)
            if used < FREE_LIMIT:
                sent = await send_one_video(uid, udoc)
                if sent:
                    await users.update_one({"user_id": uid}, {"$inc": {"free_used": 1}})
                return
            # else need ad
            token, short_url = await create_ad_session(uid)
            if not short_url:
                await q.message.reply_text("Ad provider failed. Try later.")
                return
            await send_one_video(uid, udoc, ad_token=token, ad_url=short_url)
        else:
            kb = join_group_buttons(REQUIRED_GROUP_INVITE)
            await q.message.reply_text("Still not detected as joined — please join and press I Joined.", reply_markup=kb)
        return

    # next_video, show_free, premium_menu, ad_check handled by previous handlers (keep small)
    # If needed, import and re-use previous callback logic
