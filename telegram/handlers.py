from telegram import Update
from telegram.ext import ContextTypes
from app.telegram.video_service import ensure_user, send_video

async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update.effective_user.id)
    await update.message.reply_text("Welcome! Sending your video…")
    await send_video(ctx.application, update.effective_chat.id, user)

async def next_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = await ensure_user(q.from_user.id)
    await send_video(ctx.application, q.message.chat.id, user)
