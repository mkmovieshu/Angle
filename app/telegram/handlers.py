from telegram import Update
from telegram.ext import ContextTypes
from app.telegram.bot import bot
from app.database import users, videos, ad_sessions
from app.ads.service import create_ad_session
from app.telegram.keyboards import ad_buttons, free_or_premium

FREE_LIMIT = 5  # 5 videos free

async def handle_update(data):
    update = Update.de_json(data, bot)
    if update.message:
        await handle_message(update, None)
    if update.callback_query:
        await handle_callback(update, None)


# ---------------- MESSAGE HANDLER ----------------

async def handle_message(update: Update, context):
    user = update.message.from_user
    user_id = user.id

    u = await users.find_one({"user_id": user_id})
    if not u:
        await users.insert_one({"user_id": user_id, "free_used": 0})

    u = await users.find_one({"user_id": user_id})
    used = u.get("free_used", 0)

    if used < FREE_LIMIT:
        await users.update_one(
            {"user_id": user_id},
            {"$inc": {"free_used": 1}}
        )

        vid = await videos.find_one({})
        if vid:
            await bot.send_video(chat_id=user_id, video=vid["file_id"])
        else:
            await bot.send_message(user_id, "No videos in DB")
    else:
        token, short_url = await create_ad_session(user_id)
        await bot.send_message(
            user_id,
            "You reached your free limit. Watch Ad to continue ↓",
            reply_markup=ad_buttons(short_url, token)
        )


# ---------------- CALLBACK HANDLER ----------------

async def handle_callback(update: Update, context):
    q = update.callback_query
    data = q.data
    user_id = q.from_user.id

    if data.startswith("ad_check:"):
        token = data.split(":")[1]

        rec = await ad_sessions.find_one({"token": token})

        if rec.get("status") == "completed":
            await users.update_one(
                {"user_id": user_id},
                {"$set": {"free_used": 0}}
            )
            await q.message.reply_text("✔️ Ad Verified! Videos Unlocked.")
        else:
            await q.answer("Ad Not Completed!", show_alert=True)

    elif data == "premium_menu":
        await q.message.reply_text(
            "Premium Plans:\n\n10 Days – ₹100\n20 Days – ₹150\n30 Days – ₹200"
        )
