# app/routes.py
from fastapi import APIRouter, FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, RedirectResponse, PlainTextResponse
from .telegram.handlers import ensure_user, send_video_to_user, create_ad_session
from .database import ensure_indexes, videos_col, ad_col
from .telegram.bot import bot
from .config import WEBHOOK_SECRET, ADMIN_IDS, BOT_NAME
import logging

log = logging.getLogger("video-web.routes")
router = APIRouter()

@router.get("/", response_class=PlainTextResponse)
async def index():
    return f"{BOT_NAME} service running."

@router.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"

# ad endpoints
@router.post("/ad/create")
async def ad_create(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    token, redirect = await create_ad_session(user_id)
    return JSONResponse({"token":token, "redirect_url": redirect}, status_code=201)

@router.get("/ad/redirect")
async def ad_redirect(token: str):
    await ad_col.update_one({"token": token}, {"$set":{"clicked_at": __import__("datetime").datetime.utcnow()}})
    # redirect to external AD_TARGET_URL with token param (handled by front-end)
    from .config import AD_TARGET_URL
    return RedirectResponse(f"{AD_TARGET_URL}?token={token}")

@router.post("/ad/callback")
async def ad_callback(payload: dict):
    token = payload.get("token")
    status = payload.get("status")
    if not token:
        raise HTTPException(400,"missing token")
    if status == "completed":
        await ad_col.update_one({"token": token, "status":"pending"},{"$set":{"status":"completed"}})
        return PlainTextResponse("ok")
    return PlainTextResponse("ignored")

@router.get("/ad/status/{token}")
async def ad_status(token:str):
    rec = await ad_col.find_one({"token":token})
    if not rec:
        raise HTTPException(404,"not found")
    return {"token": rec.get("token"), "status": rec.get("status","pending")}

# webhook receiver
@router.post("/webhook")
async def webhook(request: Request, x_telegram_secret: str = Header(None)):
    if WEBHOOK_SECRET and x_telegram_secret != WEBHOOK_SECRET:
        raise HTTPException(403, "invalid webhook secret")
    data = await request.json()
    # route update types
    if "message" in data:
        await __import__("app.telegram.handlers", fromlist=[""])._handle_message(data["message"])
    elif "callback_query" in data:
        await __import__("app.telegram.handlers", fromlist=[""])._handle_callback(data["callback_query"])
    elif "channel_post" in data:
        await __import__("app.telegram.handlers", fromlist=[""])._handle_channel_post(data["channel_post"])
    else:
        log.info("unknown update type keys=%s", list(data.keys()))
    return {"ok": True}
