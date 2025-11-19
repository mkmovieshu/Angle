# app/telegram/handlers_ad.py
import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import httpx

log = logging.getLogger(__name__)

BACKEND_BASE = os.getenv("DOMAIN") or os.getenv("BACKEND_URL") or ""  # DOMAIN expected (e.g., https://angle-jldx.onrender.com)
if BACKEND_BASE and not BACKEND_BASE.startswith("http"):
    BACKEND_BASE = "https://" + BACKEND_BASE

CREATE_ENDPOINT = f"{BACKEND_BASE.rstrip('/')}/ad/create-session"
GET_SESSION = f"{BACKEND_BASE.rstrip('/')}/ad/session"

async def start_ad_flow_for_user(application, chat_id: int, user_id: int, dest_url: str = None):
    """
    Call backend to create ad session, then send the shortlink + I Watched button
    """
    payload = {"user_id": user_id}
    if dest_url:
        payload["dest_url"] = dest_url

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(CREATE_ENDPOINT, json=payload)
            if r.status_code != 200:
                await application.bot.send_message(chat_id=chat_id, text="Failed to create ad session. Try again later.")
                return
            j = r.json()
        except Exception as e:
            log.exception("create session failed: %s", e)
            await application.bot.send_message(chat_id=chat_id, text="Failed to contact ad server.")
            return

    short_url = j.get("short_url") or j.get("callback_url")
    token = j.get("token")
    if not token or not short_url:
        await application.bot.send_message(chat_id=chat_id, text="Ad session could not be created.")
        return

    kb = [
        [InlineKeyboardButton("▶ Open Ad", url=short_url)],
        [InlineKeyboardButton("I Watched ✅", callback_data=f"ad_check:{token}")]
    ]
    kb_markup = InlineKeyboardMarkup(kb)
    text = "Open the ad link and after watching press *I Watched*."
    await application.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb_markup)

async def handle_ad_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if not data.startswith("ad_check:"):
        await query.answer("Invalid callback", show_alert=True)
        return
    token = data.split(":", 1)[1]

    # call backend to validate session
    check_url = f"{GET_SESSION}/{token}"
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.get(check_url)
            if r.status_code == 200:
                j = r.json()
            else:
                j = None
        except Exception as e:
            log.exception("session check failed: %s", e)
            j = None

    if not j:
        await query.answer("Could not verify. Try again in a few seconds.", show_alert=True)
        return

    if j.get("completed"):
        await query.answer("Ad already verified — unlocked!", show_alert=True)
        # perform unlock logic: e.g., reset free counter, send next video (ensure your video_service uses motor)
        uid = j.get("user_id")
        # example: calling video_service directly might be better than delegating via bot
        try:
            from app.telegram.video_service import send_one_video, ensure_user_doc
            user_doc = await ensure_user_doc(uid)
            await send_one_video(context.application, chat_id=query.message.chat.id, user_doc=user_doc)
        except Exception:
            # fallback message
            await query.message.reply_text("Ad verified — enjoy the next videos!")
        return
    else:
        # Not yet completed. Tell user to finish ad (the shortlink must ensure final redirect to callback)
        await query.answer("Ad not verified yet. Make sure you finished the ad and the page redirected back.", show_alert=True)
        # show the short url again
        short = j.get("short_url")
        if short:
            await query.message.reply_text(f"Open again: {short}")
