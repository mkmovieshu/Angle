# server.py
"""
Single FastAPI web service that:
 - handles Telegram webhook (POST /webhook)
 - serves ad endpoints: /ad/create, /ad/redirect, /ad/callback, /ad/status/{token}
 - stores data in MongoDB (motor)
 - sends videos/messages using python-telegram-bot's Bot (async)
 
Deploy on Render as a Web Service. Ensure you set TELEGRAM_WEBHOOK_URL to
https://<your-render-service>/webhook (or use full domain).
"""
import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

import motor.motor_asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, PlainTextResponse
import uvicorn
import aiohttp
from pydantic import BaseModel

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# --- Config via env
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_bot_db")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
BIN_CHANNEL = os.getenv("BIN_CHANNEL")  # optional channel id where videos are posted
FREE_BATCH = int(os.getenv("FREE_BATCH", "5"))
AD_TARGET_URL = os.getenv("AD_TARGET_URL", "https://example.com/adpage")
DOMAIN = os.getenv("DOMAIN")  # e.g. your Render service URL, used to construct redirect URL
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # optional secret to verify incoming webhook path

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env required")
if not DOMAIN:
    # not fatal, but recommended to set for correct redirect URLs
    logging.warning("DOMAIN not set. AD redirect URLs will use request host dynamically.")

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("video-web")

# Mongo
mongo = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo[DB_NAME]
users_col = db["users"]
videos_col = db["videos"]
ad_col = db["ad_sessions"]

# Telegram Bot (async)
bot = Bot(token=BOT_TOKEN)  # this uses python-telegram-bot/telegram lib async methods

app = FastAPI(title="Video Bank Web Service")

# ---------- Helpers ----------
def now():
    return datetime.utcnow()

async def ensure_user_doc(user_id: int, username: Optional[str]):
    user = await users_col.find_one({"user_id": user_id})
    if user:
        if username and user.get("username") != username:
            await users_col.update_one({"user_id": user_id}, {"$set": {"username": username}})
        # ensure fields exist
        set_fields = {}
        if "video_index" not in user:
            set_fields["video_index"] = 0
        if "free_used_in_cycle" not in user:
            set_fields["free_used_in_cycle"] = 0
        if "cycle" not in user:
            set_fields["cycle"] = 0
        if set_fields:
            await users_col.update_one({"user_id": user_id}, {"$set": set_fields})
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

def admin_check(user_id: int) -> bool:
    return user_id in ADMIN_IDS

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

# ---------- Ad endpoints ----------
class AdCreateIn(BaseModel):
    user_id: Optional[int] = None
    video_key: Optional[str] = None

@app.post("/ad/create")
async def ad_create(payload: AdCreateIn):
    """
    Create a one-time ad token and return a redirect URL.
    """
    token = uuid.uuid4().hex
    rec = {
        "token": token,
        "user_id": int(payload.user_id) if payload.user_id else None,
        "video_key": payload.video_key,
        "status": "pending",
        "created_at": now(),
        "clicked_at": None,
        "completed_at": None
    }
    await ad_col.insert_one(rec)
    host = DOMAIN or "yourdomain.com"
    redirect_url = f"https://{host}/ad/redirect?token={token}"
    return JSONResponse({"token": token, "redirect_url": redirect_url}, status_code=201)

@app.get("/ad/redirect")
async def ad_redirect(token: str, request: Request):
    """
    Logs click and redirects to the ad page (AD_TARGET_URL).
    AD_TARGET_URL should be able to call /ad/callback when ad completes.
    """
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    await ad_col.update_one({"token": token}, {"$set": {"clicked_at": now()}})
    # Attach token to AD_TARGET_URL so ad provider or your ad-page can call callback
    dst = f"{AD_TARGET_URL}?token={token}"
    return RedirectResponse(dst)

class AdCallbackIn(BaseModel):
    token: str
    status: str

@app.post("/ad/callback")
async def ad_callback(payload: AdCallbackIn, request: Request):
    """
    Called by ad-provider when rewarded ad is completed.
    payload: { token, status: "completed" }
    """
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
    return {"token": rec["token"], "status": rec.get("status", "pending")}

# ---------- Telegram webhook processing ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Main Telegram webhook endpoint. Set Telegram to POST updates here.
    Handles messages and callback_query.
    """
    data = await request.json()
    # minimal validation: if Telegram sends secret header you can verify here
    # process message or callback_query
    if "message" in data:
        await handle_message(data["message"])
    elif "callback_query" in data:
        await handle_callback(data["callback_query"])
    else:
        log.info("unsupported update type")
    return {"ok": True}

# Helper to send video by user index
async def send_video_to_user_by_index(user_id: int, idx: int):
    doc = await videos_col.find().sort("created_at", 1).skip(idx).limit(1).to_list(length=1)
    if not doc:
        return False, "no_videos"
    vdoc = doc[0]
    try:
        await bot.send_video(chat_id=user_id, video=vdoc["file_id"], caption=vdoc.get("caption", ""))
        return True, None
    except Exception as e:
        log.exception("send_video error")
        return False, str(e)

# Message handler
async def handle_message(msg: dict):
    """
    Handle incoming messages (text commands, forwarded videos)
    """
    chat = msg.get("chat", {})
    user = msg.get("from", {})
    user_id = user.get("id")
    username = user.get("username")
    text = msg.get("text", "")
    # ensure user
    udoc = await ensure_user_doc(user_id, username)

    # If admin forwarded a video or sent a video to import
    if ("forward_from_chat" in msg or "forward_from" in msg) and (msg.get("video") or msg.get("document")):
        if admin_check(user_id):
            media = msg.get("video") or msg.get("document")
            file_id = media.get("file_id")
            await videos_col.insert_one({"file_id": file_id, "caption": msg.get("caption",""), "uploader": user_id, "created_at": now()})
            await bot.send_message(chat_id=user_id, text="Imported video.")
        return

    # commands
    if text and text.startswith("/start"):
        await bot.send_message(chat_id=user_id, text="Welcome. Get 5 free videos. Use buttons.", reply_markup=make_start_keyboard())
        return

    # other text ignored for now
    return

# Callback handler
async def handle_callback(cq: dict):
    data = cq.get("data")
    from_user = cq.get("from", {})
    user_id = from_user.get("id")
    username = from_user.get("username")
    message = cq.get("message")
    msg_id = message.get("message_id") if message else None
    udoc = await ensure_user_doc(user_id, username)
    premium = await is_premium(udoc)

    # answer callback quickly
    try:
        await bot.answer_callback_query(callback_query_id=cq.get("id"))
    except Exception:
        pass

    if data == "help":
        await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Help: Free 5 -> watch ad -> next 5. Subscribe for unlimited.")
        return

    if data == "subscribe":
        await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Contact admin to subscribe.")
        return

    if data == "free_video":
        if premium:
            ok, err = await send_video_to_user_by_index(user_id, udoc.get("video_index", 0))
            if ok:
                await users_col.update_one({"user_id": user_id}, {"$inc": {"video_index": 1}})
                await bot.send_message(chat_id=user_id, text="Premium: watch next or menu.", reply_markup=make_start_keyboard())
            else:
                await bot.send_message(chat_id=user_id, text=f"Failed to send video: {err or 'none'}")
            return

        # non-premium
        if udoc.get("free_used_in_cycle", 0) < FREE_BATCH:
            ok, err = await send_video_to_user_by_index(user_id, udoc.get("video_index", 0))
            if ok:
                await users_col.update_one({"user_id": user_id}, {"$inc": {"video_index": 1, "free_used_in_cycle": 1}})
                # send Next button or ad prompt
                updated = await users_col.find_one({"user_id": user_id})
                if updated.get("free_used_in_cycle", 0) < FREE_BATCH:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Next Free Video ▶️", callback_data="free_video")]])
                    await bot.send_message(chat_id=user_id, text=f"Free videos used: {updated.get('free_used_in_cycle')} / {FREE_BATCH}", reply_markup=kb)
                else:
                    # create ad session
                    async with aiohttp.ClientSession() as s:
                        try:
                            async with s.post(f"https://{DOMAIN}/ad/create", json={"user_id": user_id}, timeout=10) as r:
                                if r.status == 201:
                                    j = await r.json()
                                    token = j.get("token")
                                    redirect = j.get("redirect_url")
                                    kb = make_ad_keyboard(redirect, token)
                                    await bot.send_message(chat_id=user_id, text=f"You used {FREE_BATCH} free videos. Watch a short ad to unlock more.", reply_markup=kb)
                                    return
                        except Exception:
                            log.exception("failed to create ad session")
                    await bot.send_message(chat_id=user_id, text="Please use the bot menu to unlock more videos.")
            else:
                await bot.send_message(chat_id=user_id, text=f"Failed to send video: {err or 'none'}")
            return

    if data and data.startswith("ad_check:"):
        token = data.split(":",1)[1]
        # check ad status
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://{DOMAIN}/ad/status/{token}", timeout=6) as r:
                    if r.status == 200:
                        js = await r.json()
                        if js.get("status") == "completed":
                            # unlock
                            await users_col.update_one({"user_id": user_id}, {"$set": {"free_used_in_cycle": 0}, "$inc": {"cycle": 1}})
                            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=f"Ad verified — unlocked next {FREE_BATCH} free videos. Press Free Video.")
                            return
                        else:
                            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Ad not verified yet. Wait a few seconds and try again.")
                            return
        except Exception:
            log.exception("ad status check failed")
        await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text="Could not verify ad. Try again later.")
        return

# ---------- health (optional) ----------
@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

# ---------- set webhook helper (not used by server automatically) ----------
async def set_telegram_webhook(webhook_url: str):
    """
    Call this once (or from your deploy script) to set the webhook for Telegram.
    webhook_url: full https URL to your deployed /webhook endpoint, e.g.
      https://<your-render-service>/webhook
    """
    result = await bot.set_webhook(url=webhook_url)
    return result

# ---------- startup (for uvicorn) ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    # when running locally, you may want to set webhook manually:
    # asyncio.run(set_telegram_webhook("https://<your-domain>/webhook"))
    uvicorn.run(app, host="0.0.0.0", port=port)
