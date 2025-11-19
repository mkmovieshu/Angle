# app/telegram/handlers_ad.py
import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.ads import service as ads_service
from app.database import users  # motor async collection
from app.telegram.video_service import send_one_video

FREE_LIMIT = int(os.getenv("FREE_LIMIT") or 5)
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT")  # "https://t.me/YourAdmin"

log = logging.getLogger(__name__)

def make_watch_keyboard(token: str, short_url: str = None, admin_contact: str = None) -> InlineKeyboardMarkup:
    buttons = []
    if short_url:
        buttons.append([InlineKeyboardButton("Watch Ad (open)", url=short_url)])
    buttons.append([InlineKeyboardButton("I Watched ✅", callback_data=f"ad_check:{token}")])
    if admin_contact:
        buttons.append([InlineKeyboardButton("Buy Premium", url=admin_contact)])
    return InlineKeyboardMarkup(buttons)

async def start_ad_flow_for_user(application, chat_id: int, user_id: int, dest_url: str = None):
    """
    Create ad session and send user the Watch Ad keyboard.
    application: telegram.ext.Application
    """
    res = ads_service.create_ad_session(user_id=user_id, dest_url=dest_url)
    token = res["token"]
    short_url = res.get("short_url")
    admin_link = ADMIN_CONTACT
    text = "To continue watching more videos you must watch an ad. Open the ad link and after watching press I Watched."
    kb = make_watch_keyboard(token, short_url, admin_link)
    await application.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

async def handle_ad_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called when user clicks "I Watched" button (callback_data ad_check:{token})
    """
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if not data.startswith("ad_check:"):
        await query.answer("Invalid callback", show_alert=True)
        return

    token = data.split(":", 1)[1]
    session = ads_service.get_session(token)
    if not session:
        await query.answer("Session not found or expired.", show_alert=True)
        return

    if not session.get("completed"):
        short_url = session.get("short_url")
        msg = "We couldn't verify your ad view yet. Open the ad link and finish the ad, then press I Watched again."
        if short_url:
            msg += f"\n\nAd link: {short_url}"
        await query.answer(text="Ad not verified", show_alert=True)
        await query.message.reply_text(msg)
        return

    # completed -> unlock logic: reset free counter
    await users.update_one({"user_id": session["user_id"]}, {"$set": {"free_used": 0}})
    await query.answer(text="Ad verified — unlocked!", show_alert=True)

    # send next video
    await send_one_video(context.application, chat_id=query.message.chat.id, user_doc={"user_id": session["user_id"], "sent_file_ids": []})
