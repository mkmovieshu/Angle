# app/telegram/handlers.py
# ============================================================
# ANGEL BOT — Telegram Handlers (FINAL, CLEAN, RENDER-READY)
# ============================================================

import uuid
import logging
from datetime import datetime
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from ..telegram.bot import bot
from ..database import users_col, videos_col, ad_col
from ..config import (
    FREE_BATCH,
    DOMAIN,
    PREMIUM_PLANS,
    SUBSCRIBE_IMAGE_URL,
    ADMIN_CONTACT_URL,
    BOT_NAME
)

log = logging.getLogger("angel.handlers")

# -------------------------------------------------------------
# UTILITIES
# -------------------------------------------------------------


def now():
    return datetime.utcnow()


async def ensure_user(user_id: int, username: str = None):
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user

    doc = {
        "user_id": user_id,
        "username": username,
        "video_index": 0,
        "free_used_in_cycle": 0,
        "cycle": 0,
        "sent_file_ids": [],
        "premium_until": None,
        "created_at": now(),
    }

    await users_col.insert_one(doc)
    return doc


async def is_premium(user):
    pu = user.get("premium_until")
    if not pu:
        return False

    if isinstance(pu, str):
        pu = datetime.fromisoformat(pu)

    return pu > now()


async def get_next_video_for_user(user):
    """Premium: get next unseen video."""
    seen = set(user.get("sent_file_ids", []))

    cursor = videos_col.find().sort("created_at", 1)
    async for v in cursor:
        fid = v["file_id"]
        if fid not in seen:
            return v

    return None


async def send_video_to_user(user_id, user):
    """Main sender: supports free + premium."""

    # PREMIUM USERS
    if await is_premium(user):
        vdoc = await get_next_video_for_user(user)

        if not vdoc:
            # reset & try again
            await users_col.update_one(
                {"user_id": user_id},
                {"$set": {"sent_file_ids": []}}
            )
            new_user = await users_col.find_one({"user_id": user_id})
            vdoc = await get_next_video_for_user(new_user)

            if not vdoc:
                return False, "no_videos"

        await bot.send_video(
            chat_id=user_id,
            video=vdoc["file_id"],
            caption=vdoc.get("caption", "")
        )

        await users_col.update_one(
            {"user_id": user_id},
            {"$push": {"sent_file_ids": vdoc["file_id"]}}
        )
        return True, None

    # FREE USERS
    idx = user.get("video_index", 0)

    docs = await videos_col.find().sort("created_at", 1).skip(idx).limit(1).to_list(1)
    if not docs:
        return False, "no_videos"

    vdoc = docs[0]

    await bot.send_video(
        chat_id=user_id,
        video=vdoc["file_id"],
        caption=vdoc.get("caption", "")
    )

    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"video_index": 1, "free_used_in_cycle": 1}}
    )

    return True, None


# -------------------------------------------------------------
# KEYBOARDS
# -------------------------------------------------------------


def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Free Video", callback_data="free_video")],
        [InlineKeyboardButton("⭐ Premium Subscription", callback_data="subscribe")],
    ])


def ad_keyboard(redirect, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Watch Ad", url=redirect)],
        [InlineKeyboardButton("✔ I Watched the Ad", callback_data=f"ad_check:{token}")],
        [InlineKeyboardButton("⭐ Go Premium (No Ads)", callback_data="subscribe")]
    ])


def subscribe_menu():
    rows = []
    for key, p in PREMIUM_PLANS.items():
        rows.append([
            InlineKeyboardButton(
                f"{p['label']} – {p['price_label']}",
                callback_data=f"show_plan:{key}"
            )
        ])
    rows.append([InlineKeyboardButton("Contact Admin", url=ADMIN_CONTACT_URL)])
    return InlineKeyboardMarkup(rows)


def plan_contact_keyboard(plan_key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Contact Admin", url=f"{ADMIN_CONTACT_URL}?plan={plan_key}")],
        [InlineKeyboardButton("⬅ Back", callback_data="subscribe_back")]
    ])


# -------------------------------------------------------------
# AD SYSTEM
# -------------------------------------------------------------


async def create_ad_session(user_id):
    token = uuid.uuid4().hex

    await ad_col.insert_one({
        "token": token,
        "user_id": user_id,
        "status": "pending",
        "created_at": now()
    })

    host = DOMAIN or "angle-jldx.onrender.com"
    redirect = f"https://{host}/ad/redirect?token={token}"

    return token, redirect


# -------------------------------------------------------------
# WEBHOOK EVENT HANDLERS  (THESE WERE MISSING PREVIOUSLY)
# -------------------------------------------------------------


async def _handle_message(msg):
    user_id = msg["chat"]["id"]
    username = msg["from"].get("username")
    text = msg.get("text", "")

    user = await ensure_user(user_id, username)

    if text == "/start":
        await bot.send_message(
            chat_id=user_id,
            text=f"👋 Welcome to {BOT_NAME}!\nChoose an option:",
            reply_markup=start_keyboard()
        )
        return

    await bot.send_message(
        chat_id=user_id,
        text="Use the buttons below 👇",
        reply_markup=start_keyboard()
    )


async def _handle_callback(cb):
    qid = cb["id"]
    data = cb["data"]
    user_id = cb["from"]["id"]
    msg_id = cb["message"]["message_id"]
    username = cb["from"].get("username")

    await bot.answer_callback_query(qid)

    user = await ensure_user(user_id, username)

    # -------------------------
    # FREE VIDEO
    # -------------------------
    if data == "free_video":
        if await is_premium(user):
            ok, err = await send_video_to_user(user_id, user)
            if not ok:
                await bot.send_message(user_id, "No more videos available.")
            return

        # free limit exceeded
        if user.get("free_used_in_cycle", 0) >= FREE_BATCH:
            token, redirect = await create_ad_session(user_id)
            await bot.edit_message_text(
                "To unlock more videos, watch this Ad:",
                chat_id=user_id,
                message_id=msg_id,
                reply_markup=ad_keyboard(redirect, token)
            )
            return

        ok, err = await send_video_to_user(user_id, user)
        if not ok:
            await bot.send_message(user_id, "No videos available.")
        return

    # -------------------------
    # AD CHECK
    # -------------------------
    if data.startswith("ad_check:"):
        token = data.split(":")[1]
        rec = await ad_col.find_one({"token": token})

        if not rec or rec.get("status") != "completed":
            await bot.send_message(user_id, "❌ You have not watched the ad fully.")
            return

        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"free_used_in_cycle": 0}}
        )

        await bot.send_message(
            user_id,
            "✅ Ad verified! You unlocked 5 more free videos.",
            reply_markup=start_keyboard()
        )
        return

    # -------------------------
    # SUBSCRIBE
    # -------------------------
    if data == "subscribe":
        await bot.edit_message_text(
            "Choose a subscription plan:",
            chat_id=user_id,
            message_id=msg_id,
            reply_markup=subscribe_menu()
        )
        return

    if data.startswith("show_plan:"):
        key = data.split(":")[1]
        plan = PREMIUM_PLANS[key]

        caption = (
            f"🔥 **{plan['label']}**\n"
            f"Duration: **{plan['days']} days**\n"
            f"Price: **{plan['price_label']}**\n\n"
            "Contact admin to activate your premium plan."
        )

        await bot.send_photo(
            chat_id=user_id,
            photo=SUBSCRIBE_IMAGE_URL,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=plan_contact_keyboard(key)
        )
        return

    if data == "subscribe_back":
        await bot.edit_message_text(
            "Choose a subscription plan:",
            chat_id=user_id,
            message_id=msg_id,
            reply_markup=subscribe_menu()
        )
        return


async def _handle_channel_post(post):
    if "video" not in post:
        return

    file_id = post["video"]["file_id"]
    caption = post.get("caption", "")
    channel_id = post["chat"]["id"]
    msg_id = post["message_id"]

    await videos_col.insert_one({
        "file_id": file_id,
        "caption": caption,
        "channel_id": channel_id,
        "message_id": msg_id,
        "created_at": now()
    })

    print("📥 Imported video:", file_id)
