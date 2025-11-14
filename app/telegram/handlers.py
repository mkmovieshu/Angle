# ----------------------------------------------------------------------------------
# REQUIRED WEBHOOK ENTRY FUNCTIONS
# These are called from FastAPI /webhook endpoint
# ----------------------------------------------------------------------------------

from telegram import Update
from telegram.constants import ParseMode
from ..telegram.bot import bot
from ..config import BOT_NAME


async def _handle_message(msg: dict):
    """Handles normal user messages."""
    user_id = msg["chat"]["id"]
    username = msg["from"].get("username")
    text = msg.get("text", "")

    user = await ensure_user(user_id, username)

    # Basic commands
    if text == "/start":
        await bot.send_message(
            chat_id=user_id,
            text=f"👋 Welcome to {BOT_NAME}!\nChoose an option:",
            reply_markup=start_keyboard()
        )
        return

    # If unknown message
    await bot.send_message(
        chat_id=user_id,
        text="Please use the menu buttons below 👇",
        reply_markup=start_keyboard()
    )


async def _handle_callback(cb: dict):
    """Handles button clicks."""
    query_id = cb["id"]
    data = cb["data"]
    user_id = cb["from"]["id"]
    msg_id = cb["message"]["message_id"]
    username = cb["from"].get("username")

    await bot.answer_callback_query(query_id)

    user = await ensure_user(user_id, username)

    # -------------------------------------------------------
    # START FREE VIDEO
    # -------------------------------------------------------
    if data == "free_video":
        # check premium or free limits
        if await is_premium(user):
            ok, err = await send_video_to_user(user_id, user)
            if not ok:
                await bot.send_message(user_id, "No videos available.")
            return

        # free users – check limit
        if user.get("free_used_in_cycle", 0) >= 5:
            token, redirect = await create_ad_session(user_id)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg_id,
                text="To unlock more videos, please watch this short ad:",
                reply_markup=ad_keyboard(redirect, token)
            )
            return

        # normal free video
        ok, err = await send_video_to_user(user_id, user)
        if not ok:
            await bot.send_message(user_id, "No videos available.")
        return

    # -------------------------------------------------------
    # WATCHED AD → CHECK
    # -------------------------------------------------------
    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_col.find_one({"token": token})
        if not rec or rec.get("status") != "completed":
            await bot.send_message(user_id, "❌ Ad not completed yet.")
            return

        # reset free cycle
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"free_used_in_cycle": 0}}
        )
        await bot.send_message(
            chat_id=user_id,
            text="✅ Ad verified! You unlocked 5 more free videos.",
            reply_markup=start_keyboard()
        )
        return

    # -------------------------------------------------------
    # SUBSCRIBE MENU
    # -------------------------------------------------------
    if data == "subscribe":
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=msg_id,
            text="Choose a premium plan:",
            reply_markup=subscribe_menu()
        )
        return

    # -------------------------------------------------------
    # SHOW PLAN DETAILS
    # -------------------------------------------------------
    if data.startswith("show_plans:"):
        plan_key = data.split(":", 1)[1]
        plan = PREMIUM_PLANS.get(plan_key, {})
        label = plan.get("label", "Premium")
        price = plan.get("price_label", "")
        days = plan.get("days", 30)

        caption = (
            f"🔥 **{label}**\n"
            f"Duration: **{days} days**\n"
            f"Price: **{price}**\n\n"
            f"Contact admin to activate your plan."
        )

        await bot.send_photo(
            chat_id=user_id,
            photo=SUBSCRIBE_IMAGE_URL,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=plan_contact_keyboard(plan_key)
        )
        return

    if data == "subscribe_back":
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=msg_id,
            text="Choose a premium plan:",
            reply_markup=subscribe_menu()
        )
        return


async def _handle_channel_post(post: dict):
    """Handles BIN channel videos → imports into DB automatically."""
    chat_id = post["chat"]["id"]
    if "video" not in post:
        return

    file_id = post["video"]["file_id"]
    caption = post.get("caption", "")

    await videos_col.insert_one({
        "file_id": file_id,
        "caption": caption,
        "channel_id": chat_id,
        "message_id": post.get("message_id"),
        "created_at": now()
    })

    print("Imported video:", file_id)
