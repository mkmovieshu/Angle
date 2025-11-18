# app/web/routes.py
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import logging
import os
import time
from pymongo import MongoClient
from urllib.parse import urlencode

from app.config import MONGO_URL, MONGO_DB_NAME, DOMAIN

logger = logging.getLogger("app.web.routes")
logging.basicConfig(level=logging.INFO)

if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env for web routes")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]
ad_sessions_col = db.get_collection("ad_sessions")

app = FastAPI()

@app.get("/ad/return", response_class=HTMLResponse)
async def ad_return(token: str = None, uid: str = None):
    """
    Called by ad provider / shortlink after user finishes ad.
    Example: GET /ad/return?token=...&uid=12345
    - Marks ad_sessions.completed = True if matching token+uid found
    - Returns a tiny HTML page that redirects back to Telegram (or thanks)
    """
    logger.info("ad/return called token=%s uid=%s", token, uid)
    if not token or not uid:
        logger.warning("ad/return missing token or uid")
        raise HTTPException(status_code=400, detail="token and uid required")

    # try to find session
    session = ad_sessions_col.find_one({"token": token, "user_id": int(uid)})
    if not session:
        # maybe token exists but uid different: try token only
        session = ad_sessions_col.find_one({"token": token})
        if not session:
            logger.warning("ad/return: session not found for token=%s uid=%s", token, uid)
            # show a generic page but don't expose details
            html = "<html><body><h3>Thanks</h3><p>We couldn't match your session. Please go back to the bot.</p></body></html>"
            return HTMLResponse(content=html, status_code=200)

    # mark completed
    try:
        ad_sessions_col.update_one({"token": token}, {"$set": {"completed": True, "completed_at": int(time.time())}})
        logger.info("ad/return: marked completed token=%s user=%s", token, uid)
    except Exception as e:
        logger.exception("ad/return: db update failed %s", e)

    # Small HTML that attempts to redirect user back to Telegram deep link or show message
    # We can redirect to tg:// or simply show a page with instructions.
    # Prefer to redirect to a neutral page (or domain root) and show message.
    # Optionally add a meta-refresh to redirect after 2s to DOMAIN or root.
    domain = DOMAIN.rstrip("/") if DOMAIN else "/"
    html = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta http-equiv="refresh" content="3;url={domain}" />
        <title>Thanks — return</title>
      </head>
      <body>
        <h3>Thanks for watching the ad</h3>
        <p>You can return to the Telegram bot now. This page will redirect shortly.</p>
        <p>If it doesn't, <a href="{domain}">click here</a>.</p>
      </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


# Admin quick route to mark a session complete (useful for manual testing)
ADMIN_SECRET = os.getenv("ADMIN_SECRET")  # set a long secret in env

@app.post("/admin/mark_ad_completed")
async def admin_mark_ad_completed(token: str, secret: str = None):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin not configured")
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    res = ad_sessions_col.find_one_and_update({"token": token}, {"$set": {"completed": True, "completed_at": int(time.time())}})
    if not res:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok", "token": token}
