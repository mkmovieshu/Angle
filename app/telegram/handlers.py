# app/telegram/handlers.py
import logging
from datetime import datetime
from typing import Optional, Any, Dict, List

from telegram import Update, Message
from telegram.error import TelegramError

from app.telegram.bot import bot
from app.database import users, videos, ad_sessions
from app.ads.service import create_ad_session
from app.telegram.keyboards import video_control_buttons
from app.config import ADMIN_CHAT_ID

log = logging.getLogger("app.telegram.handlers")
log.setLevel(logging.INFO)

FREE_LIMIT = 5  # number of free videos per cycle


def _now_iso():
    return datetime.utcnow().isoformat()


async def _ensure_user_doc(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    u = await users.find_one({"user_id": user_id})
    if u:
        # ensure sent_file_ids exists
        if "sent_file_ids" not in u:
            await users.update_one({"user_id": user_id}, {"$set": {"sent_file_ids": []}})
            u["sent_file_ids"] = []
        return u
    doc = {
        "user_id": user_id,
        "username": username,
        "free_used": 0,
        "created_at": _now_iso(),
        "premium_until": None,
        "sent_file_ids": [],  # track which file_ids we've sent to this user
    }
    await users.insert_one(doc)
    return doc


async def _get_unseen_video_for_user(user_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Return first video doc from videos collection that user hasn't received yet.
    If user has received all, return None.
    """
    sent_list: List[str] = user_doc.get("sent_file_ids", []) or []

    # Fetch some candidates (we limit to 200 to avoid huge reads)
    cursor = videos.find({}).sort("created_at", 1).limit(200)
    try:
        candidates = await cursor.to_list(length=200)
    except Exception:
        # motor may not support to_list on our FakeColl fallback; try fallback approach
        candidates = []
        async for doc in videos.find({}):
            candidates.append(doc)

    for doc in candidates:
        fid = doc.get("file_id")
        if fid and fid not in sent_list:
            return doc
    return None


async def _record_sent_file_for_user(user_id: int, file_id: str):
    # push file_id into user's sent_file_ids if not present
    await users.update_one({"user_id": user_id}, {"$addToSet": {"sent_file_ids": file_id}})


# ---------------- channel_post import ----------------
async def handle_channel_post(msg: Message):
    try:
        chat = msg.chat
        chat_id = chat.id
        file_id = None
        media_type = None

        if msg.video:
            file_id = msg.video.file_id
            media_type = "video"
        elif msg.document:
            file_id = msg.document.file_id
            media_type = "document"
        elif msg.animation:
            file_id = msg.animation.file_id
            media_type = "animation"
        elif msg.video_note:
            file_id = msg.video_note.file_id
            media_type = "video_note"

        if not file_id:
            return

        doc = {
            "file_id": file_id,
            "type": media_type,
            "caption": msg.caption or "",
            "from_channel_id": chat_id,
            "channel_post_id": msg.message_id,
            "created_at": _now_iso()
        }

        exists = await videos.find_one({"$or": [{"file_id": file_id}, {"channel_post_id": msg.message_id}]})
        if exists:
            log.info("Channel post already stored file_id=%s post=%s", file_id, msg.message_id)
            return

        await videos.insert_one(doc)
        log.info("Imported channel video file_id=%s from channel %s", file_id, chat_id)

        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Imported video from channel {chat.title or chat_id}: file_id={file_id}")
            except Exception:
                pass

    except Exception as e:
        log.exception("Error in handle_channel_post: %s", e)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Error importing channel post: {e}")
            except Exception:
                pass


# ---------------- main webhook entry ----------------
async def handle_update(raw_update: dict):
    try:
        update = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Failed to parse update JSON: %s", e)
        return

    try:
        if update.channel_post:
            await handle_channel_post(update.channel_post)
            return

        if update.message:
            await handle_message(update)
            return

        if update.callback_query:
            await handle_callback(update)
            return

    except Exception as e:
        log.exception("Unhandled error in handle_update: %s", e)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Handler error: {e}")
            except Exception:
                pass


# ---------------- send one video with control buttons ----------------
async def _send_one_video_with_controls(chat_id: int, user_doc: Dict[str, Any], ad_token: Optional[str] = None, ad_short_url: Optional[str] = None) -> bool:
    """
    Choose unseen video for user and send with control buttons (Next, Free Count, Buy Premium).
    If no unseen video, inform user.
    If ad_token/ad_short_url provided, buttons show ad options instead of Next.
    """
    # get unseen video
    vid = await _get_unseen_video_for_user(user_doc)
    if not vid:
        # user has seen all videos
        await bot.send_message(chat_id, "You have watched all available videos. We'll rotate them again soon.")
        return False

    file_id = vid.get("file_id")
    caption = vid.get("caption", "")

    try:
        # prepare buttons (if ad provided, keyboard will contain ad buttons)
        kb = video_control_buttons(token_for_ad=ad_token, ad_short_url=ad_short_url)

        # send video with reply_markup
        await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, reply_markup=kb)

        # record that we sent this file to this user
        await _record_sent_file_for_user(user_doc["user_id"], file_id)
        return True
    except TelegramError as e:
        log.exception("Failed to send video to %s: %s", chat_id, e)
        try:
            await bot.send_message(chat_id, "Failed to send video. Try again later.")
        except Exception:
            pass
        return False


# ---------------- message handler ----------------
async def handle_message(update: Update):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    user_id = user.id
    username = getattr(user, "username", None)

    u = await _ensure_user_doc(user_id, username)

    text = (msg.text or "").strip()

    if text.startswith("/start"):
        await bot.send_message(user_id, f"👋 Welcome to ANGEL! You get {FREE_LIMIT} free videos. Send any message to receive one.")
        return

    # premium check
    premium_until = u.get("premium_until")
    if premium_until:
        try:
            if isinstance(premium_until, str):
                pu = datetime.fromisoformat(premium_until)
            elif isinstance(premium_until, datetime):
                pu = premium_until
            else:
                pu = None
            if pu and pu > datetime.utcnow():
                # unlimited access: send next unseen and return
                sent = await _send_one_video_with_controls(user_id, u)
                return
        except Exception:
            log.exception("Failed to parse premium_until for user %s", user_id)

    # free-flow handling
    used = u.get("free_used", 0)
    if used < FREE_LIMIT:
        # send one and increment counter if sent
        sent_ok = await _send_one_video_with_controls(user_id, u)
        if sent_ok:
            await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
        return

    # free exhausted -> create ad session
    token, short_url = await create_ad_session(user_id)
    if not short_url:
        await bot.send_message(user_id, "Sorry — ad provider temporarily unavailable. Try again in a few moments.")
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Ad session failed: token={token} user={user_id}")
            except Exception:
                pass
        return

    # send one video but with ad buttons shown (user must watch ad)
    # fetch fresh user doc (to get latest sent_file_ids)
    u = await users.find_one({"user_id": user_id})
    await _send_one_video_with_controls(user_id, u or {"user_id": user_id, "sent_file_ids": []}, ad_token=token, ad_short_url=short_url)


# ---------------- callback handler ----------------
async def handle_callback(update: Update):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""
    user = q.from_user
    user_id = user.id

    try:
        await q.answer()
    except Exception:
        pass

    # Next video button
    if data == "next_video":
        u = await users.find_one({"user_id": user_id}) or await _ensure_user_doc(user_id, getattr(user, "username", None))
        # If user exhausted free but not watched ad, still allow next? We'll respect free count: if free_used < FREE_LIMIT send free, else require ad.
        used = u.get("free_used", 0)
        if used < FREE_LIMIT:
            sent = await _send_one_video_with_controls(user_id, u)
            if sent:
                await users.update_one({"user_id": user_id}, {"$inc": {"free_used": 1}})
            return
        else:
            # require ad: create ad session and send video with ad buttons
            token, short_url = await create_ad_session(user_id)
            if not short_url:
                await q.message.reply_text("Ad provider currently not available. Try again later.")
                return
            # send next unseen video but require ad buttons
            await _send_one_video_with_controls(user_id, u, ad_token=token, ad_short_url=short_url)
            return

    # Show free count
    if data == "show_free":
        u = await users.find_one({"user_id": user_id}) or await _ensure_user_doc(user_id, getattr(user, "username", None))
        used = u.get("free_used", 0)
        remaining = max(0, FREE_LIMIT - used)
        await q.message.reply_text(f"Free videos used: {used}\nRemaining this cycle: {remaining}")
        return

    # premium menu
    if data == "premium_menu":
        # Show plans and a small image (link). If you want a specific image file_id, set env var and code accordingly.
        photo_url = "https://i.imgur.com/0KXQZ5b.png"  # placeholder image
        text = "Premium Plans:\n\n• 10 Days – ₹100\n• 20 Days – ₹150\n• 30 Days – ₹200\n\nTo buy premium, contact the admin."
        try:
            await q.message.reply_photo(photo=photo_url, caption=text)
        except Exception:
            await q.message.reply_text(text)
        # if ADMIN_CHAT_ID present, show contact instruction
        if ADMIN_CHAT_ID:
            try:
                await q.message.reply_text(f"Contact admin: https://t.me/{ADMIN_CHAT_ID}")
            except Exception:
                pass
        return

    # Ad verify callback handled elsewhere (ad_check:token)
    if data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        rec = await ad_sessions.find_one({"token": token})
        if not rec:
            await q.answer("Ad session not found.", show_alert=True)
            return
        if rec.get("status") == "completed":
            # reset free counter and allow next videos
            await users.update_one({"user_id": user_id}, {"$set": {"free_used": 0}})
            await q.message.reply_text("✅ Ad verified — your free videos are unlocked. Enjoy!")
        else:
            await q.answer("Ad not verified yet. Click Return to Bot on the ad page and press this button again.", show_alert=True)
        return

    # fallback
    await q.answer()
