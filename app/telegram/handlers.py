# app/telegram/handlers.py

import asyncio
from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from app.telegram.bot import bot
from app.telegram.keyboards import join_group_buttons, video_control_buttons
from app.telegram.membership import is_user_member
from app.database import users, videos, ad_sessions
from app.config import REQUIRED_GROUP_ID, REQUIRED_GROUP_LINK, FREE_LIMIT


# ============================
#   FORCE JOIN CHECK
# ============================

async def handle_update(update: dict):
    """Main entry from webhook"""
    if "message" in update:
        upd = Update.de_json(update, bot)
        await handle_message(upd, None)
    elif "callback_query" in update:
        upd = Update.de_json(update, bot)
        await handle_callback(upd, None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id
    text = update.effective_message.text or ""

    # --- FORCE JOIN CHECK START ---
    member_ok = await is_user_member(chat_id)

    if not member_ok:
        await bot.send_message(
            chat_id,
            "**📌 ముందుగా మా గ్రూప్‌లో Join అవ్వాలి!**\n\n"
            "➡️ Join చేసి తిరిగి **I Joined** నొక్కండి.",
            reply_markup=join_group_buttons(REQUIRED_GROUP_LINK),
            parse_mode="Markdown"
        )
        return
    # --- FORCE JOIN CHECK END ---

    # Register user if not exist
    existing = await users.find_one({"user_id": chat_id})
    if not existing:
        await users.insert_one({
            "user_id": chat_id,
            "free_used": 0,
            "premium": False,
            "premium_expiry": None,
            "seen_videos": []
        })

    # START message
    if text == "/start":
        await send_first_video(chat_id)
        return


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = user.id
    data = query.data

    # USER JOIN CHECK
    if data == "check_join":
        ok = await is_user_member(chat_id)
        if not ok:
            await query.answer("❌ ఇంకా Join కాలేదమ్మా!", show_alert=True)
            return

        await query.answer("✅ Joined Confirmed!")

        await send_first_video(chat_id)
        return

    # Next video
    if data == "next_video":
        await query.answer()
        await send_next_video(chat_id)
        return

    # Premium Menu
    if data == "premium_menu":
        await query.answer()
        await show_premium_menu(chat_id)
        return

    # Ad confirm
    if data.startswith("ad_check:"):
        token = data.split(":")[1]
        await complete_ad_session(chat_id, token, query)
        return


# ============================
#   VIDEO SYSTEM
# ============================

async def send_first_video(chat_id: int):
    user = await users.find_one({"user_id": chat_id})
    free_used = user.get("free_used", 0)

    next_video = await videos.find_one({"index": free_used})
    if not next_video:
        await bot.send_message(chat_id, "❌ No videos found in DB.")
        return

    await bot.send_video(
        chat_id,
        next_video["file_id"],
        caption=f"🎬 **FREE VIDEO {free_used+1}/{FREE_LIMIT}**",
        parse_mode="Markdown",
        reply_markup=video_control_buttons()
    )


async def send_next_video(chat_id: int):
    user = await users.find_one({"user_id": chat_id})
    free_used = user["free_used"]

    # FREE LIMIT reached → show Ad required
    if free_used >= FREE_LIMIT:
        token, short_url = await create_ad_session(chat_id)

        await bot.send_message(
            chat_id,
            "⚠️ **Free limit complete!**\n\n"
            "➡️ యాడ్ చూడండి తర్వాత మీరు మరో వీడియో చూడొచ్చు.",
            parse_mode="Markdown",
            reply_markup=video_control_buttons(token_for_ad=token, ad_short_url=short_url)
        )
        return

    next_video = await videos.find_one({"index": free_used})
    if not next_video:
        await bot.send_message(chat_id, "❌ No more videos found.")
        return

    await bot.send_video(
        chat_id,
        next_video["file_id"],
        caption=f"🎬 **FREE VIDEO {free_used+1}/{FREE_LIMIT}**",
        parse_mode="Markdown",
        reply_markup=video_control_buttons()
    )

    await users.update_one(
        {"user_id": chat_id},
        {"$inc": {"free_used": 1}}
    )


# ============================
#   PREMIUM MENU
# ============================

async def show_premium_menu(chat_id: int):
    await bot.send_message(
        chat_id,
        "⭐ **PREMIUM PLANS** ⭐\n"
        "— Full access to all videos\n"
        "— No Ads\n\n"
        "10 days = ₹49\n"
        "20 days = ₹79\n"
        "30 days = ₹99\n\n"
        "Contact Admin to Upgrade:",
        parse_mode="Markdown",
        reply_markup=join_group_buttons("https://t.me/YourAdmin")
    )


# ============================
#   ADS SYSTEM
# ============================

async def create_ad_session(chat_id: int):
    token = str(chat_id) + "_ad"
    short_url = "https://shortxlinks.in/ad" + token[-4:]  # your generator

    await ad_sessions.insert_one({
        "user_id": chat_id,
        "token": token,
        "short_url": short_url,
        "completed": False
    })

    return token, short_url


async def complete_ad_session(chat_id: int, token: str, query):
    ad = await ad_sessions.find_one({"token": token})
    if not ad or ad.get("completed"):
        await query.answer("❌ Invalid / Already Used", show_alert=True)
        return

    await ad_sessions.update_one({"token": token}, {"$set": {"completed": True}})
    await query.answer("✅ Ad Verified")

    # Reset free limit cycle
    await users.update_one(
        {"user_id": chat_id},
        {"$set": {"free_used": 0}}
    )

    await send_first_video(chat_id)
