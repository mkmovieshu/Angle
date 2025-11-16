# app/ads/service.py
import os
import logging
import uuid
import httpx
from datetime import datetime

from app.database import ad_sessions
from app.config import SHORTX_API_KEY

log = logging.getLogger("ads.service")


async def create_ad_session(user_id: int):
    """
    Create an ad session for the user.
    Returns (token, short_url) or (token, None) if provider unavailable.
    Stores record in ad_sessions collection with 'completed': False
    """
    token = uuid.uuid4().hex
    short_url = None

    # Try provider if API key present
    if SHORTX_API_KEY:
        try:
            # Example ShortX API (adjust if yours is different)
            # We post to their endpoint with api key & destination URL (use a safe fallback)
            dest = f"https://example.com/ad-landing?token={token}"
            url = f"https://shortxlinks.com/api"
            params = {"api": SHORTX_API_KEY, "url": dest}
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and data.get("status") in ("success", "ok") and data.get("shortenedUrl"):
                        short_url = data.get("shortenedUrl")
                    else:
                        log.warning("Shortx responded but no usable short_url: %s", data)
                else:
                    log.warning("Shortx HTTP %s: %s", r.status_code, r.text)
        except Exception as e:
            log.exception("Shortx call failed: %s", e)

    # fallback short_url if provider not used
    if not short_url:
        # create an internal "virtual" short url you control (front-end not necessary)
        short_url = f"https://{os.getenv('DOMAIN')}/ad/{token}"

    doc = {
        "token": token,
        "user_id": user_id,
        "short_url": short_url,
        "completed": False,
        "created_at": datetime.utcnow().isoformat(),
    }
    await ad_sessions.insert_one(doc)
    log.info("Ad session created token=%s user=%s short=%s", token, user_id, short_url)
    return token, short_url


async def mark_ad_completed(token: str, user_id: int) -> bool:
    """
    Mark ad session completed if exists and belongs to user.
    Returns True if changed from False->True.
    """
    rec = await ad_sessions.find_one({"token": token, "user_id": user_id})
    if not rec:
        return False
    if rec.get("completed"):
        return False
    await ad_sessions.update_one({"token": token}, {"$set": {"completed": True, "completed_at": datetime.utcnow().isoformat()}})
    log.info("Ad session completed token=%s user=%s", token, user_id)
    return True
