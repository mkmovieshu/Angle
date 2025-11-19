from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from app.ads import service

router = APIRouter()

@router.post("/ad/create-session")
async def create(payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id missing")

    session = await service.create_ad_session(user_id)
    return {
        "token": session["token"],
        "short_url": session["short_url"] or session["callback_url"],
        "callback_url": session["callback_url"]
    }

@router.get("/ad/callback/{token}", response_class=HTMLResponse)
async def cb(token: str):
    await service.mark_completed(token)
    return "<h2>Ad verified — you can return to the bot.</h2>"

@router.get("/ad/session/{token}")
async def session_info(token: str):
    s = await service.get_session(token)
    if not s:
        raise HTTPException(status_code=404)
    return {"completed": s["completed"], "user_id": s["user_id"], "short_url": s["short_url"]}
