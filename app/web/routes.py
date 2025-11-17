# app/web/routes.py
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from app.ads.service import get_session, mark_completed

app = FastAPI()

@app.get("/", response_class=PlainTextResponse)
async def root():
    return "ANGEL ad endpoints live"

@app.get("/ad/landing/{token}", response_class=HTMLResponse)
async def ad_landing(token: str):
    """
    Optional landing page shown to user after they click short link.
    Should display instructions and a return button that points to /ad/complete/{token}
    """
    session = get_session(token)
    if not session:
        return HTMLResponse("<h3>Invalid ad token</h3>", status_code=404)
    # Simple page - you can customize
    html = f"""
    <html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>
    <h3>Watch the ad — then click Return</h3>
    <p>If the provider did not callback us automatically, click the button after you finished the ad.</p>
    <a href="{session.get('return_url')}" style="display:inline-block;padding:12px;background:#2b90d9;color:#fff;border-radius:6px;text-decoration:none;">Return to bot (complete)</a>
    </body></html>
    """
    return HTMLResponse(html)

@app.get("/ad/complete/{token}", response_class=PlainTextResponse)
async def ad_complete(token: str):
    """
    Provider or user returning to this URL should mark session completed.
    Mark completed and return a small message.
    """
    s = get_session(token)
    if not s:
        raise HTTPException(status_code=404, detail="token not found")
    mark_completed(token)
    return PlainTextResponse("Ad session marked completed. You may return to the bot and press I Watched.")

@app.post("/provider/webhook/shortx")
async def shortx_webhook(request: Request):
    """
    Example provider server-to-server webhook.
    Provider should send data identifying the short link or alias; 
    this endpoint must validate signature if provider provides one.
    """
    body = await request.json()
    # Provider specific logic here: try to find token in body or alias field
    # Example: body might contain 'alias': 'adabcdef'
    alias = body.get("alias") or body.get("shortcode") or body.get("shortened")
    # attempt to extract token from alias if we used 'ad{token[:8]}' pattern
    token = None
    if alias and alias.startswith("ad"):
        token_candidate = alias[2:]
        # try to match existing session by short alias prefix
        from app.ads.service import ad_sessions
        doc = ad_sessions.find_one({"token": {"$regex": f"^{token_candidate}"}})
        if doc:
            token = doc["token"]
    # fallback: provider might send full url
    if not token:
        # try find by full short_url
        short_url = body.get("shortenedUrl") or body.get("short_url") or body.get("url")
        if short_url:
            from app.ads.service import ad_sessions
            doc = ad_sessions.find_one({"short_url": short_url})
            if doc:
                token = doc["token"]
    if not token:
        return {"status": "ignored", "reason": "no token matched"}
    mark_completed(token, provider_payload=body)
    return {"status": "ok", "token": token}
