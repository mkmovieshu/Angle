from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.telegram.handlers import handle_update
from app.ads.service import mark_ad_completed
from app.config import DOMAIN

router = APIRouter()

@router.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    await handle_update(data)
    return {"ok": True}

@router.get("/ad/return")
async def ad_return(token: str, uid: int):
    await mark_ad_completed(token)

    html = f"""
    <html><body style='text-align:center;font-family:Arial'>
    <h2>🎉 Ad Completed</h2>
    <p>Tap button below to return to ANGEL Bot</p>
    <a href="https://t.me/mk_post0_bot?start=ad_{token}">
        <button style='padding:10px 20px;'>Return to Bot</button>
    </a>
    </body></html>
    """
    return HTMLResponse(html)
