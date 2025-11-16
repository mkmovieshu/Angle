# app/ads/service.py
import uuid
import aiohttp
import urllib.parse
import logging
from datetime import datetime
from typing import Optional, Tuple, Any, Dict

from app.database import ad_sessions
from app.config import SHORTX_API_KEY, DOMAIN

log = logging.getLogger("app.ads.service")
log.setLevel(logging.INFO)

def utcnow() -> datetime:
    return datetime.utcnow()


async def create_ad_session(user_id: int) -> Tuple[str, Optional[str]]:
    """
    Create an ad session record and ask ShortXLinks to create a short link.
    Returns (token, short_url_or_none).
    Stores provider raw response in ad_sessions.provider_response for debugging.
    """
    token = uuid.uuid4().hex
    return_url = f"https://{DOMAIN}/ad/return?token={token}&uid={user_id}"
    params = {
        "api": SHORTX_API_KEY,
        "url": return_url,
        "alias": f"ad{token[:6]}"
    }

    short_api = "https://shortxlinks.com/api?" + urllib.parse.urlencode(params)

    # create DB record first (so we always have token)
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
            async with s.get(short_api, timeout=20) as resp:
                # try parse JSON; if fails, capture text for debugging
                try:
                    js = await resp.json()
                except Exception:
                    text = await resp.text()
                    log.error("ShortX returned non-json response for token=%s: %s", token, text[:1000])
                    # save raw text and mark failed
                    await ad_sessions.update_one(
                        {"token": token},
                        {"$set": {"status": "failed", "provider_response": text}}
                    )
                    return token, None

                # store raw provider response for debugging
                await ad_sessions.update_one(
                    {"token": token},
                    {"$set": {"provider_response": js}}
                )

                # quick debug log (visible in Render logs)
                log.error("RAW_SHORTX_RESPONSE token=%s: %s", token, repr(js)[:2000])

                # Normalise and extract a string short_url from many possible shapes.
                short_url = _extract_short_url(js)

                if not short_url:
                    log.error("No usable short_url found in provider response for token=%s: %s", token, js)
                    # mark failed so we don't retry blindly
                    await ad_sessions.update_one(
                        {"token": token},
                        {"$set": {"status": "failed"}}
                    )
                    return token, None

                # Save the extracted redirect_url and return it
                await ad_sessions.update_one(
                    {"token": token},
                    {"$set": {"redirect_url": short_url}}
                )
                return token, short_url

    except Exception as e:
        log.exception("Exception while creating ad session for token=%s: %s", token, e)
        await ad_sessions.update_one(
            {"token": token},
            {"$set": {"status": "failed", "provider_response": str(e)}}
        )
        return token, None


def _extract_short_url(js: Any) -> Optional[str]:
    """
    Try many heuristics to pull a usable short link string from the provider response.
    Return string or None.
    """
    # if provider returned a string (rare)
    if isinstance(js, str) and js.strip().startswith("http"):
        return js.strip()

    # if it's a dict try many known keys
    if isinstance(js, dict):
        # direct string keys
        candidates = ["shortenedUrl", "short_url", "short", "url", "data", "shortlink", "shortId"]
        for k in candidates:
            v = js.get(k)
            if isinstance(v, str) and v.strip().startswith("http"):
                return v.strip()
            # sometimes v is nested dict with the actual url
            if isinstance(v, dict):
                for kk in ("short", "short_url", "url", "link", "shortenedUrl"):
                    vv = v.get(kk)
                    if isinstance(vv, str) and vv.strip().startswith("http"):
                        return vv.strip()
        # sometimes response shape: {"data": {"url": "..."}}
        d = js.get("data")
        if isinstance(d, dict):
            for kk in ("short", "url", "link", "short_url"):
                vv = d.get(kk)
                if isinstance(vv, str) and vv.strip().startswith("http"):
                    return vv.strip()

        # some providers embed under top-level 'result' or 'response'
        for topk in ("result", "response", "value"):
            topv = js.get(topk)
            if isinstance(topv, dict):
                for kk in ("short", "url", "link", "short_url"):
                    vv = topv.get(kk)
                    if isinstance(vv, str) and vv.strip().startswith("http"):
                        return vv.strip()

        # fallback: scan the entire dict values for a string that looks like a url
        for val in js.values():
            if isinstance(val, str) and val.strip().startswith("http"):
                return val.strip()

    # can't find anything usable
    return None


async def mark_ad_completed(token: str) -> None:
    """
    Mark ad session as completed. Called by /ad/return endpoint when provider redirects user back.
    """
    await ad_sessions.update_one(
        {"token": token},
        {"$set": {"status": "completed", "completed_at": utcnow()}}
    )
