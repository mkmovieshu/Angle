import os
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from app.telegram.video_service import ensure_user, send_video

DOMAIN = os.getenv("DOMAIN").rstrip("/")
SESSION_URL = DOMAIN + "/ad/session"

async def handle_ad_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    token = update.callback_query.data.split(":")[1]
    url = f"{SESSION_URL}/{token}"

    async with httpx.AsyncClient() as c:
        r = await c.get(url)
        if r.status_code != 200:
            await update.callback_query.answer("Try again…")
            return
        info = r.json()

    if not info.get("completed"):
        await update.callback_query.answer("Ad not finished!")
        return

    await update.callback_query.answer("Verified!")

    user = await ensure_user(info["user_id"])
    await send_video(ctx.application, update.effective_chat.id, user)
