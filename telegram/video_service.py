# telegram/video_service.py
import logging
from database import users, videos  # root-level database.py provides motor collections
from telegram.keyboards import next_btn, ad_btn

log = logging.getLogger(__name__)

async def ensure_user(uid: int):
    u = await users.find_one({"user_id": uid})
    if not u:
        u = {"user_id": uid, "sent": [], "free_used": 0}
        await users.insert_one(u)
    return u

async def send_video(application, chat_id: int, user):
    sent = user.get("sent", [])
    v = await videos.find_one({"file_id": {"$nin": sent}})
    if not v:
        await application.bot.send_message(chat_id, "No more videos available.")
        return

    fid = v["file_id"]
    kb = next_btn()
    try:
        await application.bot.send_video(chat_id=chat_id, video=fid, caption=v.get("caption", ""), reply_markup=kb)
        await users.update_one({"user_id": user["user_id"]}, {"$push": {"sent": fid}})
    except Exception as e:
        log.exception("Failed to send video: %s", e)
        try:
            await application.bot.send_message(chat_id, "Failed to send video. Try later.")
        except Exception:
            pass
