# app/web/ad_routes.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import logging
from app.ads import service as ads_service

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/ad/create-session")
async def api_create_session(payload: dict):
    """
    Expected JSON payload:
    { "user_id": 12345, "dest_url": "https://example.com/ads/123", "meta": {...} }
    Returns: { "token": "...", "short_url": "https://..." , "callback_url": "https://..."}
    """
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    dest = payload.get("dest_url")
    meta = payload.get("meta")
    res = await ads_service.create_ad_session(user_id=int(user_id), dest_url=dest, meta=meta)
    return JSONResponse(res)

@router.get("/ad/callback/{token}", response_class=HTMLResponse)
async def ad_callback(token: str, request: Request):
    """
    This endpoint should be the final landing that the shortlink ultimately redirects to
    after the ad is viewed. It marks session completed.
    It returns a small HTML page that thanks the user and optionally redirects to dest_url.
    """
    session = await ads_service.get_session(token)
    if not session:
        return HTMLResponse("<h3>Invalid or expired session</h3>", status_code=404)

    # mark completed (idempotent)
    changed = await ads_service.mark_completed(token)

    dest = session.get("dest_url")
    # Simple HTML: show a thank you + optional redirect back to dest (or to a friendly page)
    body = "<html><head><meta charset='utf-8'><title>Thanks</title></head><body>"
    body += "<h2>Thanks — Ad Verified</h2><p>You may now return to the bot.</p>"
    if dest:
        body += f"<p>If you'd like, <a href='{dest}'>continue to the page</a>.</p>"
    body += "<script>setTimeout(function(){window.close && window.close();},1500);</script>"
    body += "</body></html>"
    return HTMLResponse(body)

@router.get("/ad/session/{token}")
async def get_session(token: str):
    s = await ads_service.get_session(token)
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    # Do not leak internal fields
    return {
        "token": s["token"],
        "user_id": s["user_id"],
        "completed": bool(s.get("completed")),
        "short_url": s.get("short_url"),
        "callback_url": s.get("callback_url"),
    }
