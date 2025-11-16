# app/telegram/handlers.py
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update, Message
from telegram.error import TelegramError

from app.telegram.bot import bot
from app.telegram.membership import is_user_member
from app.telegram.video_service import ensure_user_doc, send_one_video, record_sent
from app.telegram.keyboards import join_group_buttons, video_control_buttons
from app.ads.service import create_ad_session, mark_ad_completed
from app.database import users, videos, ad_sessions
from app.config import FREE_LIMIT, REQUIRED_GROUP_LINK

log = logging.getLogger("handlers")
log.setLevel(logging.INFO)


async def handle_update(raw_update: dict):
    try:
        upd = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Invalid update JSON: %s", e)
        return

    if upd.channel_post:
        # channel imports handled elsewhere (channel_import)
        from app.telegram.channel_import import import_channel_post
        try:
            await import_channel_post(upd.channel_post)
        except Exception:
            log.exception("channel import failed")
        return

    if upd.message:
        await handle_message(upd)
        return

    if upd.callback_query:
        await handle_callback(upd)
        return


async def handle_message(update: Update):
    msg: Message = update.message
    if not msg:
        return

    user = msg.from_user
    user_id = user.id
    username = getattr(user, "username", None)
    await ensure_user_doc(user_id, username)
    text = (msg.text or "").strip()

    # Force join
    if not await is_user_member(user_id):
        kb = join_group_buttons(REQUIRED_GROUP_LINK)
        await bot.send_message(user_id, "📌 ముందుగా మా గ్రూప్‌లో Join అవ్వాలి!\nJoin చేసి 'I Joined' నొక్కండి.", reply_markup=kb)
        return

    # /start
    if text.startswith("/start"):
        await bot.send_message(user_id, f"👋 Welcome to ANGEL! You get {FREE_LIMIT} free videos. Send any message to receive one.")
        return

    # Premium check (if premium_until exists and not expired)
    u = await users.find_one({"user_id": user_id})
    premium_until = u.get("premium_until") if u else None
    if premium_until:
        try:
            pu = datetime.fromisoformat(premium_until) if isinstance(premium_until, str) else premium_until
            if pu and pu > datetime.utcnow():
                await send_one_video(user_id, u)
                return
        except Exception:
            log.exception("premium parse fail")

    # Free quota logic
    used = u.get("free_used", 0) if u else 0

    if used < FREE_LIMIT:
        sent = await send_one_video(user_id, u)
        if sent:
            # increment free_used AFTER successful send
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> create ad session and send ad-call-to-action (no video)
    token, short_url = await create_ad_session(user_id)
    if not short_url:
        await bot.send_message(user_id, "Sorry — ad provider temporarily unavailable. Try again later.")
        return

    kb = video_control_buttons(token_for_ad=token, ad_short_url=short_url)
    await bot.send_message(user_id, "⚠️ Free limit reached. Watch an ad to unlock the next set of videos.", reply_markup=kb)


async def handle_callback(update: Update):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    user_id = q.from_user.id

    # always answer quickly to avoid 'loading' in client
    try:
        await q.answer()
    except Exception:
        pass

    # I Joined (re-check group membership)
    if data == "check_join":
        if await is_user_member(user_id):
            await q.message.reply_text("✅ Membership confirmed. Sending video now.")
            u = await ensure_user_doc(user_id, getattr(q.from_user, "username", None))
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
            await q.message.reply_text("Free limit reached. Watch ad to continue.", reply_markup=video_control_buttons(token_for_ad=token, ad_short_url=short_url))
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
        # If free exhausted -> send ad CTA
        token, short_url = await create_ad_session(user_id)
        if not short_url:
            await q.message.reply_text("Ad provider unavailable. Try later.")
            return
        await q.message.reply_text("Free limit reached. Watch ad to continue.", reply_markup=video_control_buttons(token_for_ad=token, ad_short_url=short_url))
        return

    # Show free count
    if data == "show_free":
        u = await users.find_one({"user_id": user_id}) or await ensure_user_doc(user_id)
        used = u.get("free_used", 0)
        await q.message.reply_text(f"Used: {used}\nRemaining: {max(0, FREE_LIMIT - used)}")
        return

    # Premium menu
    if data == "premium_menu":
        await q.message.reply_text("⭐ Premium plans: contact admin to subscribe.")
        return

    # Ad check — user clicked "I Watched"
    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        # mark ad completed in db (auth by token+user)
        changed = await mark_ad_completed(token, user_id)
        if not changed:
            # maybe the record is already completed or doesn't exist
            rec = await ad_sessions.find_one({"token": token})
            if not rec:
                await q.message.reply_text("❌ Ad session not found or expired.")
                return
            if rec.get("completed"):
                # already completed — proceed
                pass
            else:
                # fallback: mark it now anyway
                await ad_sessions.update_one({"token": token}, {"$set": {"completed": True}})
        # reset free cycle: set free_used to 0 so user can get next FREE_LIMIT videos
        await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
        await q.message.reply_text("✅ Ad verified — unlocking next free videos.")
        # send first video of new cycle
        u = await users.find_one({"user_id": user_id}) or await ensure_user_doc(user_id)
        sent = await send_one_video(user_id, u)
        if sent:
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return
