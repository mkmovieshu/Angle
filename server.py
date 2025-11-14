# server.py
"""
Single-file FastAPI web service for:
 - Telegram webhook (POST /webhook)
 - Ad endpoints: /ad/create, /ad/redirect, /ad/callback, /ad/status/{token}
 - MongoDB via motor (async)
 - Sending messages/videos via python-telegram-bot's async Bot
 - Health and root routes
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Optional

import motor.motor_asyncio
import aiohttp
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------
# Configuration (from env)
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "video_bot_db")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
BIN_CHANNEL = os.getenv("BIN_CHANNEL", None)
FREE_BATCH = int(os.getenv("FREE_BATCH", "5"))
AD_TARGET_URL = os.getenv("AD_TARGET_URL", "https://example.com/adpage")
DOMAIN = os.getenv("DOMAIN", None)  # optional; if not set will derive from request
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # optional, not enforced here

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env required")

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("video-web")

# ---------------------------
# Mongo init (motor)
# ---------------------------
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
users_col = db["users"]
videos_col = db["videos"]
ad_col = db["ad_sessions"]

# ---------------------------
# Telegram Bot (async)
# ---------------------------
bot = Bot(token=BOT_TOKEN)  # python-telegram-bot's Bot supports async methods in v20+

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
    """Ensure user doc exists and has required fields."""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        # ensure necessary fields present
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
# Pydantic models for ad callbacks
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
    """
    Create an ad session token and return redirect URL.
    Redirect URL will be built using DOMAIN env var if set, otherwise the current request host.
    """
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

    # Build redirect host
    if DOMAIN:
        host = DOMAIN
    else:
        # derive from request
        url = request.url
        host = url.netloc
    redirect_url = f"https://{host}/ad/redirect?token={token}"
    return JSONResponse({"token": token, "redirect_url": redirect_url}, status_code=201)

@app.get("/ad/redirect")
async def ad_redirect(token: str):
    """
    Logs click and redirects to AD_TARGET_URL with token appended.
    AD_TARGET_URL should be an ad page that will call /ad/callback when ad is completed.
    """
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    await ad_col.update_one({"token": token}, {"$set": {"clicked_at": now()}})
    # attach token to AD_TARGET_URL so ad-host can callback
    dst = f"{AD_TARGET_URL}?token={token}"
    return RedirectResponse(dst)

@app.post("/ad/callback")
async def ad_callback(payload: AdCallbackIn):
    """
    Called by ad-provider or your ad page when ad completed.
    Payload: {"token":"...", "status":"completed"}
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
    return {"token": rec.get("token"), "status": rec.get("status", "pending")}

# ---------------------------
# Telegram webhook endpoint
# ---------------------------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram will POST updates here (messages, callback_query).
    We parse and dispatch to handlers.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # basic routing of update types
    if "message" in data:
        await _handle_message(data["message"])
    elif "callback_query" in data:
        await _handle_callback(data["callback_query"])
    else:
        log.info("Unhandled update type")
    return {"ok": True}

# ---------------------------
# Internal helpers: send video by index
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
    """
    Handle incoming messages (commands, forwarded videos).
    Admins can forward video messages to import into videos collection.
    """
    user = msg.get("from", {}) or {}
    user_id = user.get("id")
    username = user.get("username")
    chat = msg.get("chat", {}) or {}
    text = msg.get("text", "") or ""

    # ensure user
    if user_id is None:
        log.info("message without user")
        return
    udoc = await ensure_user_doc(user_id, username)

    # admin forwarding import flow
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

    # other messages ignored for now
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

    # ack callback quickly
    try:
        await bot.answer_callback_query(callback_query_id=cq.get("id"))
    except Exception:
        pass

    udoc = await ensure_user_doc(user_id, username)
    premium = await is_premium(udoc)

    # help / subscribe
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

    # free_video flow
    if data == "free_video":
        # premium gets next video without ad gating
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

        # non-premium gating
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
                    # create ad session and send ad keyboard
                    # use our own ad/create endpoint to create token & redirect
                    host = DOMAIN or "yourdomain.com"
                    # if DOMAIN not set, use service host derived from bot (can't here) - rely on ad_create route for correct redirect
                    try:
                        # call our ad/create endpoint internally via HTTP to get redirect (so token is generated server-side)
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

    # ad_check token verification
    if data and data.startswith("ad_check:"):
        token = data.split(":", 1)[1]
        # check ad status via our endpoint
        host = DOMAIN or "yourdomain.com"
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
# Set webhook helper (call once if you prefer)
# ---------------------------
async def set_telegram_webhook(webhook_url: str):
    """
    Use this helper to set webhook programmatically if needed.
    """
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
    # run with uvicorn programmatically
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
