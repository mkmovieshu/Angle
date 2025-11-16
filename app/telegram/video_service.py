# app/telegram/video_service.py
import logging
from typing import Optional, Dict, Any, List
from telegram.error import TelegramError
from app.telegram.bot import bot
from app.database import users, videos
from app.telegram.keyboards import video_control_buttons

log = logging.getLogger("video_service")

async def ensure_user_doc(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    u = await users.find_one({"user_id": user_id})
    if u:
        if "sent_file_ids" not in u:
            await users.update_one({"user_id": user_id}, {"$set": {"sent_file_ids": []}})
            u["sent_file_ids"] = []
        return u
    doc = {"user_id": user_id, "username": username, "free_used": 0, "premium_until": None, "sent_file_ids": []}
    await users.insert_one(doc)
    return doc

async def get_unseen_video_for_user(user_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sent: List[str] = user_doc.get("sent_file_ids", []) or []
    cursor = videos.find({}).sort("created_at", 1).limit(200)
    try:
        candidates = await cursor.to_list(length=200)
    except Exception:
        candidates = []
        async for d in videos.find({}):
            candidates.append(d)
    for d in candidates:
        fid = d.get("file_id")
        if fid and fid not in sent:
            return d
    return None

async def record_sent(user_id: int, file_id: str):
    await users.update_one({"user_id": user_id}, {"$addToSet": {"sent_file_ids": file_id}})

async def send_one_video(chat_id: int, user_doc: Dict[str, Any], ad_token: Optional[str]=None, ad_url: Optional[str]=None) -> bool:
    vid = await get_unseen_video_for_user(user_doc)
    if not vid:
        await bot.send_message(chat_id, "No unseen videos available right now. Check later.")
        return False
    file_id = vid["file_id"]
    caption = vid.get("caption", "")
    kb = video_control_buttons(token_for_ad=ad_token, ad_short_url=ad_url)
    try:
        await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, reply_markup=kb)
        await record_sent(user_doc["user_id"], file_id)
        return True
    except TelegramError as e:
        log.exception("send_one_video error: %s", e)
        try:
            await bot.send_message(chat_id, "Failed to deliver video. Try later.")
        except Exception:
            pass
        return False
