# app/telegram/handlers.py
import uuid
import logging
from datetime import datetime, timedelta
from ..database import users_col, videos_col, ad_col
from ..telegram.bot import bot
from ..telegram.keyboards import start_keyboard, ad_keyboard, subscribe_menu, plan_contact_keyboard
from ..config import FREE_BATCH, DOMAIN, PREMIUM_PLANS, ADMIN_IDS, BOT_NAME
import aiohttp

log = logging.getLogger("video-web.handlers")

def now():
    return datetime.utcnow()

async def ensure_user(user_id:int, username: str=None):
    user = await users_col.find_one({"user_id":user_id})
    if user:
        return user
    doc = {
        "user_id": user_id,
        "username": username,
        "video_index": 0,
        "free_used_in_cycle": 0,
        "cycle": 0,
        "sent_file_ids": [],   # to prevent repeats for premium users
        "premium_until": None,
        "created_at": now()
    }
    await users_col.insert_one(doc)
    return doc

async def is_premium(user_doc) -> bool:
    pu = user_doc.get("premium_until")
    if not pu:
        return False
    if isinstance(pu, str):
        pu = datetime.fromisoformat(pu)
    return pu > now()

# choose next unseen video for user (premium avoids repeats)
async def get_next_video_for_user(user_doc):
    # fetch all videos
    sent = set(user_doc.get("sent_file_ids", []))
    # first try find a video not in sent
    cursor = videos_col.find().sort("created_at",1)
    async for v in cursor:
        fid = v.get("file_id")
        if fid not in sent:
            return v
    # if all sent, return None (or optionally allow looping by clearing sent)
    return None

# send video helper (for both free and premium)
async def send_video_to_user(user_id:int, user_doc):
    # premium: get unseen
    if await is_premium(user_doc):
        vdoc = await get_next_video_for_user(user_doc)
        if not vdoc:
            # all seen — clear sent_file_ids to allow loop (or keep empty to stop)
            # here we choose to clear so premium users can see again after full cycle
            await users_col.update_one({"user_id":user_id}, {"$set":{"sent_file_ids":[]}})
            user_doc = await users_col.find_one({"user_id":user_id})
            vdoc = await get_next_video_for_user(user_doc)
            if not vdoc:
                return False, "no_videos"
        try:
            await bot.send_video(chat_id=user_id, video=vdoc["file_id"], caption=vdoc.get("caption",""))
            await users_col.update_one({"user_id":user_id}, {"$push":{"sent_file_ids": vdoc["file_id"]}})
            return True, None
        except Exception as e:
            log.exception("send_video error")
            return False, str(e)
    # non-premium: behave as before using video_index
    else:
        idx = user_doc.get("video_index",0)
        docs = await videos_col.find().sort("created_at",1).skip(idx).limit(1).to_list(length=1)
        if not docs:
            return False, "no_videos"
        vdoc = docs[0]
        try:
            await bot.send_video(chat_id=user_id, video=vdoc["file_id"], caption=vdoc.get("caption",""))
            await users_col.update_one({"user_id":user_id},{"$inc":{"video_index":1,"free_used_in_cycle":1}})
            return True, None
        except Exception as e:
            log.exception("send_video error_non_premium")
            return False, str(e)

# create ad session in DB (internal)
async def create_ad_session(user_id:int, video_key=None):
    token = uuid.uuid4().hex
    rec = {
        "token": token,
        "user_id": user_id,
        "video_key": video_key,
        "status": "pending",
        "created_at": now(),
        "clicked_at": None,
        "completed_at": None
    }
    await ad_col.insert_one(rec)
    host = DOMAIN or "angle-ylzn.onrender.com"
    redirect = f"https://{host}/ad/redirect?token={token}"
    return token, redirect
