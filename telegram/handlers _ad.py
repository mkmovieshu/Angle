# telegram/handlers_ad.py
import os
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegram.video_service import ensure_user, send_video

DOMAIN = os.getenv("DOMAIN", "").rstrip("/")
SESSION_URL = DOMAIN + "/ad/session"

async def handle_ad_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    token = query.data.split(":", 1)[1]
    url = f"{SESSION_URL}/{token}"

    async with httpx.AsyncClient() as c:
        try:
            r = await c.get(url)
            if r.status_code != 200:
                await query.answer("Could not verify. Try again later.", show_alert=True)
                return
            info = r.json()
        except Exception:
            await query.answer("Verification failed (network). Try again.", show_alert=True)
            return

    if not info.get("completed"):
        await query.answer("Ad not finished!", show_alert=True)
        return

    await query.answer("Verified!")
    user = await ensure_user(info["user_id"])
    await send_video(ctx.application, query.message.chat.id, user)
