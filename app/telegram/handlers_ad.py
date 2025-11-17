# app/telegram/handlers_ad.py
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.ads import service as ads_service
from app.database import users, videos  # adjust according to your repo

FREE_LIMIT = int(os.getenv("FREE_LIMIT") or 5)

def make_watch_keyboard(token: str, short_url: str = None, admin_contact: str = None):
    buttons = []
    if short_url:
        buttons.append([InlineKeyboardButton("Watch Ad (open)", url=short_url)])
    # I Watched button calls callback to check DB
    buttons.append([InlineKeyboardButton("I Watched ✅", callback_data=f"ad_check:{token}")])
    # Premium / contact admin
    if admin_contact:
        buttons.append([InlineKeyboardButton("Buy Premium", url=admin_contact)])
    return InlineKeyboardMarkup(buttons)

async def start_ad_flow_for_user(bot, chat_id: int, user_id: int, dest_url: str = None):
    """
    Create ad session and send user the Watch Ad keyboard.
    """
    res = ads_service.create_ad_session(user_id=user_id, dest_url=dest_url)
    token = res["token"]
    short_url = res.get("short_url")
    # admin contact (telegram link) from env
    admin_link = os.getenv("ADMIN_CONTACT")  # e.g. "https://t.me/YourAdmin"
    text = "To continue watching more videos you must watch an ad. Open the ad link and after watching press I Watched."
    kb = make_watch_keyboard(token, short_url, admin_link)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

async def handle_ad_check_callback(bot, update, callback_query):
    """
    Called when user clicks "I Watched" button (callback_data ad_check:{token})
    """
    data = callback_query.data or ""
    if not data.startswith("ad_check:"):
        return False
    token = data.split(":", 1)[1]
    session = ads_service.get_session(token)
    if not session:
        await callback_query.answer("Session not found or expired.", show_alert=True)
        return True
    if not session.get("completed"):
        # not yet completed, show message and (if available) short_url again
        short_url = session.get("short_url")
        msg = "We couldn't verify your ad view yet. Open the ad link and finish the ad, then press I Watched again."
        if short_url:
            msg += f"\n\nAd link: {short_url}"
        await callback_query.answer(text="Ad not verified", show_alert=True)
        await callback_query.message.reply_text(msg)
        return True

    # completed -> unlock logic: reset free counter or send next videos
    # Example: set user's free count to 0 so they can get next free videos
    users.update_one({"user_id": session["user_id"]}, {"$set": {"free_used": 0}})
    await callback_query.answer(text="Ad verified — unlocked!", show_alert=True)
    # send next video — you must implement send_next_free_video(user_id, chat_id)
    from app.telegram.video_sender import send_next_free_video
    await send_next_free_video(bot=bot, user_id=session["user_id"], chat_id=callback_query.message.chat.id)
    return True
