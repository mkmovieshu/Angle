# app/ads/service.py
import uuid
import aiohttp
import urllib.parse
import logging
from datetime import datetime
from app.database import ad_sessions
from app.config import SHORTX_API_KEY, DOMAIN

log = logging.getLogger("app.ads.service")

def utcnow():
    return datetime.utcnow()

async def create_ad_session(user_id: int):
    token = uuid.uuid4().hex
    return_url = f"https://{DOMAIN}/ad/return?token={token}&uid={user_id}"
    params = {
        "api": SHORTX_API_KEY,
        "url": return_url,
        "alias": f"ad{token[:5]}"
    }
    short_api = "https://shortxlinks.com/api?" + urllib.parse.urlencode(params)

    # create DB record
    await ad_sessions.insert_one({
        "token": token,
        "user_id": user_id,
        "status": "pending",
        "redirect_url": None,
        "provider_response": None,
        "created_at": utcnow(),
        "completed_at": None
    })

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(short_api, timeout=20) as r:
                # try parse json safely
                try:
                    js = await r.json()
                except Exception:
                    text = await r.text()
                    log.error("Shortx returned non-json response: %s", text)
                    await ad_sessions.update_one({"token": token}, {"$set": {"status": "failed", "provider_response": text}})
                    return token, None

                # store raw provider response for debugging
                await ad_sessions.update_one({"token": token}, {"$set": {"provider_response": js}})

                # NORMALIZE: extract string short_url from common shapes
                short_url = None
                # common keys to check
                for k in ("shortenedUrl", "short_url", "short", "data", "url"):
                    v = js.get(k) if isinstance(js, dict) else None
                    if isinstance(v, str) and v.strip():
                        short_url = v.strip()
                        break
                    # some providers return nested dict like {"data": {"short": "https://..."}}
                    if isinstance(v, dict):
                        for kk in ("short", "short_url", "url"):
                            vv = v.get(kk)
                            if isinstance(vv, str) and vv.strip():
                                short_url = vv.strip()
                                break
                        if short_url:
                            break

                # fallback: sometimes response is just a string
                if not short_url and isinstance(js, str) and js.strip():
                    short_url = js.strip()

                if not short_url:
                    # nothing useful — mark failed and return None
                    log.error("Could not find short_url in provider response: %s", js)
                    await ad_sessions.update_one({"token": token}, {"$set": {"status": "failed"}})
                    return token, None

                # save and return
                await ad_sessions.update_one({"token": token}, {"$set": {"redirect_url": short_url}})
                return token, short_url

    except Exception as e:
        log.exception("Failed to create ad session")
        await ad_sessions.update_one({"token": token}, {"$set": {"status": "failed", "provider_response": str(e)}})
        return token, None


async def mark_ad_completed(token: str):
    await ad_sessions.update_one(
        {"token": token},
        {"$set": {"status": "completed", "completed_at": utcnow()}}
    )
