# app/routes.py
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.status import HTTP_302_FOUND
import logging

from app.database import ad_sessions
from app.ads.service import mark_ad_completed

app = FastAPI()
log = logging.getLogger("routes")


@app.get("/", response_class=PlainTextResponse)
async def root():
    return PlainTextResponse("ANGEL service is running. Use /webhook for Telegram updates.")


@app.get("/ad/landing/{token}", response_class=HTMLResponse)
async def ad_landing(token: str):
    """
    Internal landing page shown when provider fallback used.
    This page should instruct user to watch ad on partner provider,
    or can redirect automatically to provider URL if you configure one.
    After ad playback completes provider should redirect to /ad/complete/{token}
    """
    # Provide a simple page that instructs user and gives a button to 'I have watched' that returns user to /ad/complete
    html = f"""
    <html>
      <head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
      <body style="font-family: Arial; text-align:center; padding:20px;">
        <h2>Watch the short ad to unlock more videos</h2>
        <p>Click the button below to open the ad page (or your provider). After watching the ad, you'll be redirected back to unlock videos.</p>
        <a href="/ad/complete/{token}" style="display:inline-block;padding:12px 20px;background:#2b90d9;color:white;border-radius:8px;text-decoration:none;">I've finished watching (Return)</a>
        <p style="margin-top:12px;color:#666;font-size:14px;">If your provider redirects back automatically, you'll be redirected here.</p>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/ad/complete/{token}", response_class=HTMLResponse)
async def ad_complete(token: str, request: Request):
    """
    Provider or the user returns to this URL after ad view.
    We will mark the token completed in DB.
    Show a simple page telling user to go back to Telegram and press I Watched (or we can auto-open tg).
    """
    try:
        # mark completed (no user_id from HTTP request — we don't have Telegram user in this call)
        await ad_sessions.update_one({"token": token}, {"$set": {"completed": True, "completed_at": __import__("datetime").datetime.utcnow().isoformat()}})
    except Exception as e:
        log.exception("Failed marking ad complete for token=%s: %s", token, e)

    # A friendly page: tell user to return to Telegram
    bot_link = ""
    try:
        # If DOMAIN contains bot username or you can add tg link
        bot_link = f"tg://resolve?domain=ANGEL"  # optional: replace with actual bot username or use https t.me/...
    except Exception:
        bot_link = ""

    html = f"""
    <html>
      <head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
      <body style="font-family: Arial; text-align:center; padding:20px;">
        <h2>Thanks — Ad view recorded</h2>
        <p>You may now return to Telegram and press <b>I Watched</b> to unlock more videos.</p>
        <p><a href="{bot_link or '#'}" style="display:inline-block;padding:12px 20px;background:#2b90d9;color:white;border-radius:8px;text-decoration:none;">Open Telegram</a></p>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
