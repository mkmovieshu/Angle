# server.py
"""
FastAPI web service for:
 - Telegram webhook (POST /webhook) handling: message, callback_query, channel_post
 - Ad endpoints: /ad/create, /ad/redirect, /ad/callback, /ad/status/{token}
 - Admin debug endpoints: list/insert videos
 - MongoDB (motor) async integration
 - Sends messages/videos via python-telegram-bot async Bot
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Optional

import motor.motor_asyncio
import aiohttp
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import RedirectResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------
# Config (env)
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_bot_db")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
BIN_CHANNEL = os.getenv("BIN_CHANNEL", None)  # optional channel id to copy posts (not used by default)
FREE_BATCH = int(os.getenv("FREE_BATCH", "5"))
AD_TARGET_URL = os.getenv("AD_TARGET_URL", "https://example.com/adpage")
DOMAIN = os.getenv("DOMAIN", None)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # optional secret for Telegram webhook verification

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env required")

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("video-web")

# ---------------------------
# Mongo (motor)
# ---------------------------
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
users_col = db["users"]
videos_col = db["videos"]
ad_col = db["ad_sessions"]

# create useful indexes (idempotent)
async def ensure_indexes():
    try:
        await videos_col.create_index([("file_id", 1)], unique=False)
        await videos_col.create_index([("channel_id", 1), ("message_id", 1)], unique=True, sparse=True)
        await ad_col.create_index([("token", 1)], unique=True)
        await users_col.create_index([("user_id", 1)], unique=True)
    except Exception:
        log.exception("ensure_indexes failed")

# ---------------------------
# Telegram Bot (async)
# ---------------------------
bot = Bot(token=BOT_TOKEN)

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI(title="Video Bank Web Service")

# ---------------------------
# Helpers
# ---------------------------
def now():
    return datetime.utcnow()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def ensure_user_doc(user_id: int, username: Optional[str]):
    user = await users_col.find_one({"user_id": user_id})
    if user:
        set_fields = {}
        if "video_index" not in user:
            set_fields["video_index"] = 0
        if "free_used_in_cycle" not in user:
            set_fields["free_used_in_cycle"] = 0
        if "cycle" not in user:
            set_fields["cycle"] = 0
        if set_fields:
            await users_col.update_one({"user_id": user_id}, {"$set": set_fields})
        if username and user.get("username") != username:
            await users_col.update_one({"user_id": user_id}, {"$set": {"username": username}})
        return await users_col.find_one({"user_id": user_id})
    doc = {
        "user_id": user_id,
        "username": username,
        "premium_until": None,
        "video_index": 0,
        "free_used_in_cycle": 0,
        "cycle": 0,
        "created_at": now(),
    }
    await users_col.insert_one(doc)
    return doc

async def is_premium(user_doc) -> bool:
    pu = user_doc.get("premium_until")
    if not pu:
        return False
    if isinstance(pu, str):
        try:
            pu = datetime.fromisoformat(pu)
        except Exception:
            return False
    return pu > now()

def make_start_keyboard():
    kb = [
        [InlineKeyboardButton("Free Video 🎁", callback_data="free_video")],
        [InlineKeyboardButton("Subscribe (premium)", callback_data="subscribe")],
        [InlineKeyboardButton("Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

def make_ad_keyboard(redirect_url: str, token: str):
    kb = [
        [InlineKeyboardButton("Open Short Ad 🔗", url=redirect_url)],
        [InlineKeyboardButton("I watched the ad ✅", callback_data=f"ad_check:{token}")],
    ]
    return InlineKeyboardMarkup(kb)

# ---------------------------
# Pydantic models
# ---------------------------
class AdCreateIn(BaseModel):
    user_id: Optional[int] = None
    video_key: Optional[str] = None

class AdCallbackIn(BaseModel):
    token: str
    status: str

# ---------------------------
# Root & health
# ---------------------------
@app.on_event("startup")
async def startup_event():
    log.info("Application startup: ensuring DB indexes")
    await ensure_indexes()

@app.get("/", response_class=PlainTextResponse)
async def index():
    return "Angle service is running. Use /healthz or POST /webhook for Telegram updates."

@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"

# ---------------------------
# Ad endpoints
# ---------------------------
@app.post("/ad/create")
async def ad_create(payload: AdCreateIn, request: Request):
    token = uuid.uuid4().hex
    rec = {
        "token": token,
        "user_id": int(payload.user_id) if payload.user_id else None,
        "video_key": payload.video_key,
        "status": "pending",
        "created_at": now(),
        "clicked_at": None,
        "completed_at": None,
    }
    await ad_col.insert_one(rec)

    if DOMAIN:
        host = DOMAIN
    else:
        host = request.url.netloc
    redirect_url = f"https://{host}/ad/redirect?token={token}"
    return JSONResponse({"token": token, "redirect_url": redirect_url}, status_code=201)

@app.get("/ad/redirect")
async def ad_redirect(token: str):
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    await ad_col.update_one({"token": token}, {"$set": {"clicked_at": now()}})
    dst = f"{AD_TARGET_URL}?token={token}"
    return RedirectResponse(dst)

@app.post("/ad/callback")
async def ad_callback(payload: AdCallbackIn):
    token = payload.token
    status = payload.status
    if not token:
        raise HTTPException(status_code=400, detail="missing token")
    if status == "completed":
        await ad_col.update_one({"token": token, "status": "pending"}, {"$set": {"status": "completed", "completed_at": now()}})
        return PlainTextResponse("ok")
    return PlainTextResponse("ignored")

@app.get("/ad/status/{token}")
async def ad_status(token: str):
    rec = await ad_col.find_one({"token": token})
    if not rec:
        raise HTTPException(status_code=404, detail="not found")
    return {"token": rec.get("token"), "status": rec.get("status", "pending")}

# ---------------------------
# Admin debug endpoints (temporary)
# ---------------------------
def _admin_check_simple(admin_id: int) -> bool:
    return admin_id in ADMIN_IDS

@app.get("/admin/list_videos")
async def admin_list_videos(admin_id: int):
    if not _admin_check_simple(admin_id):
        raise HTTPException(status_code=403, detail="forbidden")
    docs = await videos_col.find().sort("created_at", -1).to_list(length=200)
    items = [{"_id": str(d.get("_id")), "file_id": d.get("file_id"), "caption": d.get("caption"), "channel_id": d.get("channel_id")} for d in docs]
    return {"count": len(items), "videos": items}

@app.post("/admin/insert_video")
async def admin_insert_video(admin_id: int, file_id: str, caption: Optional[str] = ""):
    if not _admin_check_simple(admin_id):
        raise HTTPException(status_code=403, detail="forbidden")
    rec = {"file_id": file_id, "caption": caption, "uploader": admin_id, "created_at": now()}
    res = await videos_col.insert_one(rec)
    return {"inserted_id": str(res.inserted_id)}

# ---------------------------
# Telegram webhook handler
# ---------------------------
@app.post("/webhook")
async def telegram_webhook(request: Request, x_telegram_secret: Optional[str] = Header(None)):
    # optional secret validation
    if WEBHOOK_SECRET:
        if x_telegram_secret != WEBHOOK_SECRET:
            log.warning("Invalid webhook secret header")
            raise HTTPException(status_code=403, detail="invalid webhook secret")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # route update types
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    elif "channel_post" in data:
        await _handle_channel_post(data["channel_post"])
    else:
        log.info("Unhandled update type: keys=%s", list(data.keys()))
    return {"ok": True}

# ---------------------------
# Video sending helper
# ---------------------------
async def send_video_to_user_by_index(user_id: int, idx: int):
    docs = await videos_col.find().sort("created_at", 1).skip(idx).limit(1).to_list(length=1)
    if not docs:
        return False, "no_videos"
    vdoc = docs[0]
    try:
        await bot.send_video(chat_id=user_id, video=vdoc["file_id"], caption=vdoc.get("caption", ""))
        return True, None
    except Exception as e:
        log.exception("send_video error")
        return False, str(e)

# ---------------------------
# Message handler
# ---------------------------
async def _handle_message(msg: dict):
    user = msg.get("from", {}) or {}
    user_id = user.get("id")
    username = user.get("username")
    text = msg.get("text", "") or ""

    if user_id is None:
        log.info("message without user")
        return

    udoc = await ensure_user_doc(user_id, username)

    # admin forwarding import (legacy)
    if ("forward_from_chat" in msg or "forward_from" in msg) and (msg.get("video") or msg.get("document")):
        if is_admin(user_id):
            media = msg.get("video") or msg.get("document")
            file_id = media.get("file_id")
            await videos_col.insert_one({"file_id": file_id, "caption": msg.get("caption",""), "uploader": user_id, "created_at": now()})
            try:
                await bot.send_message(chat_id=user_id, text="Imported video.")
            except Exception:
                pass
        return

    # commands
    if text.startswith("/start"):
        try:
            await bot.send_message(chat_id=user_id, text="Welcome. Get 5 free videos. Use buttons.", reply_markup=make_start_keyboard())
        except Exception:
            log.exception("failed to send welcome")
        return

    return

# ---------------------------
# Callback handler
# ---------------------------
async def _handle_callback(cq: dict):
    data = cq.get("data")
    from_user = cq.get("from", {}) or {}
    user_id = from_user.get("id")
    username = from_user.get("username")
    message = cq.get("message") or {}
    msg_id = message.get("message_id")

    if user_id is None:
        return

    try:
        await bot.answer_callback_query(callback_query_id=cq.get("id"))
    except Exception:
        pass

    udoc = await ensure_user_doc(user_id, username)
    premium = await is_premium(udoc)

    # simple helpers
    if data == "help":
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Help: Free 5 -> watch ad -> next 5. Subscribe for unlimited.")
        except Exception:
            pass
        return

    if data == "subscribe":
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Contact admin to subscribe.")
        except Exception:
            pass
        return

    if data == "free_video":
        if premium:
            ok, err = await send_video_to_user_by_index(user_id, udoc.get("video_index", 0))
            if ok:
                await users_col.update_one({"user_id": user_id}, {"$inc": {"video_index": 1}})
                try:
                    await bot.send_message(chat_id=user_id, text="Premium: watch next or menu.", reply_markup=make_start_keyboard())
                except Exception:
                    pass
            else:
                try:
                    await bot.send_message(chat_id=user_id, text=f"Failed to send video: {err or 'unknown'}")
                except Exception:
                    pass
            return

        # non-premium flow
        if udoc.get("free_used_in_cycle", 0) < FREE_BATCH:
            ok, err = await send_video_to_user_by_index(user_id, udoc.get("video_index", 0))
            if ok:
                await users_col.update_one({"user_id": user_id}, {"$inc": {"video_index": 1, "free_used_in_cycle": 1}})
                updated = await users_col.find_one({"user_id": user_id})
                if updated.get("free_used_in_cycle", 0) < FREE_BATCH:
                    try:
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Next Free Video ▶️", callback_data="free_video")]])
                        await bot.send_message(chat_id=user_id, text=f"Free videos used: {updated.get('free_used_in_cycle')} / {FREE_BATCH}", reply_markup=kb)
                    except Exception:
                        pass
                    return
                else:
                    # create ad session internally
                    try:
                        # construct ad/create using service host
                        host = DOMAIN or "localhost"
                        async with aiohttp.ClientSession() as s:
                            async with s.post(f"https://{host}/ad/create", json={"user_id": user_id}, timeout=10) as resp:
                                if resp.status == 201:
                                    j = await resp.json()
                                    token = j.get("token")
                                    redirect = j.get("redirect_url")
                                    kb = make_ad_keyboard(redirect, token)
                                    await bot.send_message(chat_id=user_id, text=f"You used {FREE_BATCH} free videos. Watch a short ad to unlock more.", reply_markup=kb)
                                    return
                    except Exception:
                        log.exception("failed to create ad session")
                    try:
                        await bot.send_message(chat_id=user_id, text="Please use the bot menu to unlock more videos.")
                    except Exception:
                        pass
                    return
            else:
                try:
                    await bot.send_message(chat_id=user_id, text=f"Failed to send video: {err or 'unknown'}")
                except Exception:
                    pass
                return

    if data and data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        host = DOMAIN or "localhost"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://{host}/ad/status/{token}", timeout=6) as resp:
                    if resp.status == 200:
                        js = await resp.json()
                        if js.get("status") == "completed":
                            await users_col.update_one({"user_id": user_id}, {"$set": {"free_used_in_cycle": 0}, "$inc": {"cycle": 1}})
                            try:
                                await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=f"Ad verified — unlocked next {FREE_BATCH} free videos. Press Free Video.")
                            except Exception:
                                pass
                            return
                        else:
                            try:
                                await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Ad not verified yet. Wait a few seconds and try again.")
                            except Exception:
                                pass
                            return
        except Exception:
            log.exception("ad_status check failed")
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Could not verify ad. Try again later.")
        except Exception:
            pass
        return

# ---------------------------
# Channel post handler (automatic import from BIN channel)
# ---------------------------
async def _handle_channel_post(post: dict):
    """
    Handle channel_post updates: insert video/doc into videos_col automatically.
    Bot must be admin in the channel for these updates to arrive.
    """
    try:
        chat = post.get("chat", {}) or {}
        chat_id = chat.get("id")
        message_id = post.get("message_id")

        media = post.get("video") or post.get("document")
        if not media:
            log.info("channel_post ignored: no media (chat_id=%s, msg_id=%s)", chat_id, message_id)
            return

        file_id = media.get("file_id")
        caption = post.get("caption", "")

        if not file_id:
            log.warning("channel_post media missing file_id (chat_id=%s, msg_id=%s)", chat_id, message_id)
            return

        # avoid duplicates by channel_id+message_id or file_id
        existing = await videos_col.find_one({"$or":[{"file_id": file_id}, {"channel_id": chat_id, "message_id": message_id}]})
        if existing:
            log.info("channel_post already exists in DB, skipping: file_id=%s", file_id)
            return

        rec = {
            "file_id": file_id,
            "caption": caption,
            "uploader": None,
            "channel_id": chat_id,
            "message_id": message_id,
            "imported_via": "channel_post",
            "created_at": now()
        }
        res = await videos_col.insert_one(rec)
        log.info("Imported channel_post video into DB id=%s file_id=%s", res.inserted_id, file_id)

        # Optionally forward or copy to BIN_CHANNEL if desired:
        # if BIN_CHANNEL and str(chat_id) != str(BIN_CHANNEL):
        #     try:
        #         await bot.forward_message(chat_id=BIN_CHANNEL, from_chat_id=chat_id, message_id=message_id)
        #     except Exception:
        #         log.exception("forward to BIN_CHANNEL failed")

    except Exception:
        log.exception("Exception in _handle_channel_post")

# ---------------------------
# Webhook helper to set webhook (optional)
# ---------------------------
async def set_telegram_webhook(webhook_url: str):
    try:
        return await bot.set_webhook(url=webhook_url)
    except Exception:
        log.exception("set_webhook failed")
        raise

# ---------------------------
# Uvicorn entrypoint
# ---------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
