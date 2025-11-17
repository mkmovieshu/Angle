# app/telegram/handlers.py
import os
import logging
import traceback
from typing import Dict, Any, Optional

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.error import TelegramError
from telegram.constants import ParseMode

from pymongo import MongoClient

# ---- Config from env ----
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")  # you wanted MONGO_URL, not MONGO_URI
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))  # channel id where videos are forwarded
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "5"))  # number of free videos before ad gating
DOMAIN = os.getenv("DOMAIN", "")  # optional, used in links

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN required in env")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")
if not BIN_CHANNEL:
    logging.warning("BIN_CHANNEL not set (or set to 0) - bin importer won't work until set")

# ---- Bot & DB init ----
bot = Bot(token=BOT_TOKEN)
client = MongoClient(MONGO_URL)
db = client.get_default_database()  # expects a DB in the URL or uses default DB name
# Collections used:
users_col = db.get_collection("users")
videos_col = db.get_collection("bin_videos")  # bin_importer should populate this

# ---- Logging ----
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# -------------------------
# Utilities
# -------------------------
def _make_main_keyboard():
    kb = [
        [InlineKeyboardButton("🎬 Videos", callback_data="open_videos")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)


def _make_video_controls(index: int, total: int, show_next: bool = True):
    kb = []
    if show_next:
        kb.append(InlineKeyboardButton("▶️ Next", callback_data=f"next|{index}"))
    kb.append(InlineKeyboardButton("🔖 My Status", callback_data="status"))
    return InlineKeyboardMarkup([kb])


def get_user_state(user_id: int) -> Dict[str, Any]:
    u = users_col.find_one({"user_id": user_id})
    if not u:
        u = {
            "user_id": user_id,
            "video_index": 0,
            "ads_watched": 0,
        }
        users_col.insert_one(u)
    return u


def set_user_state(user_id: int, **fields):
    users_col.update_one({"user_id": user_id}, {"$set": fields}, upsert=True)


def increment_user_index(user_id: int, delta: int = 1):
    users_col.update_one({"user_id": user_id}, {"$inc": {"video_index": delta}}, upsert=True)


# -------------------------
# Core behavior
# -------------------------
async def handle_update(raw_update: Dict[str, Any]):
    """
    Entrypoint used by routes.py -> handle_update(data)
    raw_update is the update JSON from Telegram (webhook).
    """
    try:
        update = Update.de_json(raw_update, bot)
    except Exception as e:
        log.exception("Failed to parse Update")
        return

    try:
        # Message handlers
        if update.message:
            await _handle_message(update.message)
        elif update.callback_query:
            await _handle_callback(update.callback_query)
        else:
            log.info("Unhandled update type: %s", type(update))
    except Exception as e:
        log.error("Error handling update: %s", e)
        log.debug(traceback.format_exc())


async def _handle_message(message: Message):
    user_id = message.from_user.id
    text = message.text or ""
    chat_id = message.chat.id

    # /start
    if text.startswith("/start"):
        await bot.send_message(
            chat_id=chat_id,
            text=f"👋 Hi {message.from_user.first_name}!\n\nWelcome — use the menu below.",
            reply_markup=_make_main_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    # If user types Videos (some clients) fallback
    if text.lower().strip() in ("videos", "video", "🎬 videos"):
        # emulate button press
        await _open_videos_for_user(user_id=user_id, chat_id=chat_id)
        return

    # unknown text -> show menu
    await bot.send_message(
        chat_id=chat_id,
        text="I didn't understand. Choose from the menu.",
        reply_markup=_make_main_keyboard(),
    )


# -------------------------
# Callback handling
# -------------------------
async def _handle_callback(query):
    data = query.data or ""
    user = query.from_user
    chat_id = query.message.chat.id

    try:
        if data == "open_videos":
            await query.answer()  # remove 'loading'
            await _open_videos_for_user(user_id=user.id, chat_id=chat_id)
            return

        if data.startswith("next|"):
            # format: next|<last_sent_index>
            try:
                _, prev_index = data.split("|", 1)
                prev_index = int(prev_index)
            except Exception:
                prev_index = None
            await query.answer()
            await _send_next_video(user.id, chat_id, prev_sent_index=prev_index)
            return

        if data == "status":
            u = get_user_state(user.id)
            await query.answer()
            await bot.send_message(
                chat_id=chat_id,
                text=f"📊 Your status:\n• Videos viewed (index): {u.get('video_index',0)}\n• Ads watched: {u.get('ads_watched',0)}",
            )
            return

        if data == "help":
            await query.answer()
            await bot.send_message(
                chat_id=chat_id,
                text="Help: Click Videos → then Next to navigate. After free limit you'll be asked to watch an ad.",
            )
            return

        # unknown callback
        await query.answer("Unknown action", show_alert=False)
    except TelegramError as te:
        log.exception("Telegram error in callback: %s", te)
        try:
            await query.answer("Action failed")
        except Exception:
            pass
    except Exception:
        log.exception("Unhandled callback exception")


# -------------------------
# Video serving logic
# -------------------------
def _get_videos_for_bin(limit: int = 100):
    """
    Return ordered list of video docs from videos_col for BIN_CHANNEL.
    Each doc expected to have at least: { 'file_id': str, 'caption': str (opt), 'date': <ts> }
    """
    query = {"channel_id": BIN_CHANNEL} if BIN_CHANNEL else {}
    cursor = videos_col.find(query).sort("date", -1).limit(limit)
    return list(cursor)


async def _open_videos_for_user(user_id: int, chat_id: int):
    """
    Called when user opens the videos menu.
    Resets index for the user (optional) or continues from stored index.
    Sends the first video (according to user.video_index).
    """
    u = get_user_state(user_id)
    # ensure videos exist
    vids = _get_videos_for_bin(limit=500)
    if not vids:
        await bot.send_message(chat_id=chat_id, text="No videos found right now. Admin, check importer.")
        return

    # send the current video for this user
    index = int(u.get("video_index", 0))
    if index >= len(vids):
        # reached end -> reset or inform
        await bot.send_message(chat_id=chat_id, text="You've reached the end of available videos.")
        return

    # check free limit gating
    if index >= FREE_LIMIT:
        # need ad gating
        await _prompt_watch_ad(user_id, chat_id)
        return

    # send the video at index
    vid = vids[index]
    await _send_video_doc(chat_id, vid, index, total=len(vids))


async def _send_next_video(user_id: int, chat_id: int, prev_sent_index: Optional[int]):
    """
    When user presses Next; we verify that prev_sent_index matches stored index to prevent skipping ads
    """
    u = get_user_state(user_id)
    stored_index = int(u.get("video_index", 0))

    # If prev_sent_index doesn't match stored index (user tries to fake) -> enforce stored_index
    if prev_sent_index is None or prev_sent_index != stored_index:
        # force them to continue from saved index
        index = stored_index
    else:
        index = stored_index + 1
        set_user_state(user_id, video_index=index)

    vids = _get_videos_for_bin(limit=500)
    if index >= len(vids):
        await bot.send_message(chat_id=chat_id, text="No more videos available.")
        return

    # gating
    if index >= FREE_LIMIT:
        await _prompt_watch_ad(user_id, chat_id)
        return

    vid = vids[index]
    await _send_video_doc(chat_id, vid, index, total=len(vids))


async def _send_video_doc(chat_id: int, vid_doc: Dict[str, Any], index: int, total: int):
    """
    Sends a video message (uses file_id stored in DB). Adds inline Next/status controls.
    """
    try:
        file_id = vid_doc.get("file_id")
        caption = vid_doc.get("caption", "")
        if not file_id:
            await bot.send_message(chat_id=chat_id, text="Video record is malformed (no file_id).")
            return

        # send video by file_id (assumes it is a telegram file_id)
        await bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption + f"\n\n🔢 {index+1}/{total}",
            reply_markup=_make_video_controls(index=index, total=total, show_next=True),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        log.exception("Failed to send video to chat %s", chat_id)
        await bot.send_message(chat_id=chat_id, text="Failed to send video (check bot permissions).")


# -------------------------
# Ad gating helpers
# -------------------------
async def _prompt_watch_ad(user_id: int, chat_id: int):
    """
    Prompt the user to watch ad sessions. This integrates with your ad-session flow.
    We send an inline keyboard with 'Watch Ad' and 'Buy Premium' options.
    """
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("▶️ Watch Ad", callback_data="watch_ad"),
                InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium"),
            ],
            [InlineKeyboardButton("🔁 Restart from beginning", callback_data="restart_videos")],
        ]
    )
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "⚠️ You reached the free limit.\n\n"
            "Watch a short ad to unlock more videos, or buy premium to remove limits."
        ),
        reply_markup=kb,
    )


# Callback handlers for ad/watch/purchase should be connected here.
# Minimal implementations:
async def _handle_watch_ad_callback(query):
    user = query.from_user
    await query.answer()
    # NOTE: integrate with your shortx/ad-session APIs here.
    # After user completes ad flow and bot receives confirmation (webhook from shortx or callback),
    # you MUST call mark_ad_completed(user_id) to increment ads_watched and allow next videos.
    await bot.send_message(chat_id=query.message.chat.id, text="📺 Opened ad session (placeholder). After ad completes, bot will resume videos.")


async def _handle_buy_premium_callback(query):
    await query.answer()
    await bot.send_message(chat_id=query.message.chat.id, text="💎 Premium purchase flow (placeholder). Please contact admin.")


# Connect watch_ad & buy_premium callbacks in main callback handler above:
# add inside _handle_callback: if data == "watch_ad": await _handle_watch_ad_callback(query)
# if data == "buy_premium": await _handle_buy_premium_callback(query)
# if data == "restart_videos": set_user_state(user.id, video_index=0) and send first video


# -------------------------
# Admin helper: mark ad completed (called from ads.service or external webhook)
# -------------------------
def mark_ad_completed(user_id: int, extra_videos: int = 5):
    """
    Call this function (synchronously) when ad provider notifies that user watched ad fully.
    Increments ads_watched and grants extra_videos by increasing FREE_LIMIT for that user (or decrease gating).
    This function is available for import by your ads.service module.
    """
    users_col.update_one({"user_id": user_id}, {"$inc": {"ads_watched": 1, "video_index": -extra_videos}}, upsert=True)
    # video_index decreased so user can see next videos; alternative designs possible


# expose for imports
__all__ = ["handle_update", "mark_ad_completed", "bot"]
