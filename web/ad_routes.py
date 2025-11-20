# web/ad_routes.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from ads import service as ads_service

router = APIRouter()

@router.post("/ad/create-session")
async def create(payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id missing")
    session = await ads_service.create_ad_session(int(user_id))
    return {
        "token": session["token"],
        "short_url": session.get("short_url") or session["callback_url"],
        "callback_url": session["callback_url"]
    }

@router.get("/ad/callback/{token}", response_class=HTMLResponse)
async def cb(token: str):
    await ads_service.mark_completed(token)
    return "<h2>Ad verified — you can return to the bot.</h2>"

@router.get("/ad/session/{token}")
async def session_info(token: str):
    s = await ads_service.get_session(token)
    if not s:
        raise HTTPException(status_code=404)
    return {"completed": s.get("completed", False), "user_id": s["user_id"], "short_url": s.get("short_url")}
