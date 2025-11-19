# app/ads/service.py
import os
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
import json

import httpx
from app.database import ad_sessions  # motor async collection

log = logging.getLogger(__name__)

# Env (these names preserved per your memory)
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "")
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")
SHORTLINK_API_MODE = os.getenv("SHORTLINK_API_MODE", "query")  # "query" | "json" | "format"
SHORTLINK_API_KEY_PARAM = os.getenv("SHORTLINK_API_KEY_PARAM", "api")  # param name for API key if needed
DOMAIN = os.getenv("DOMAIN", "").rstrip("/")  # your domain, used for callback
SHORTLINK_TIMEOUT = float(os.getenv("SHORTLINK_TIMEOUT", "10"))

def _make_callback_url(token: str) -> str:
    if DOMAIN:
        return f"{DOMAIN}/ad/callback/{token}"
    # fallback local path
    return f"/ad/callback/{token}"

async def _call_shortlink_provider(target_url: str) -> Optional[str]:
    """
    Call the shortlink provider in a flexible way.
    Modes:
    - "query": GET to SHORTLINK_API_URL with params {SHORTLINK_API_KEY_PARAM: SHORTLINK_API_KEY, 'url': target_url}
    - "json": POST JSON body {'key': SHORTLINK_API_KEY, 'url': target_url}
    - "format": SHORTLINK_API_URL is a template containing {url} or {target}, e.g. "https://tnlink.in/info?longurl={url}&api={api}"
    """
    if not SHORTLINK_API_URL:
        log.info("SHORTLINK_API_URL not set — returning target_url as short_url")
        return target_url

    async with httpx.AsyncClient(timeout=SHORTLINK_TIMEOUT) as client:
        try:
            mode = (SHORTLINK_API_MODE or "query").lower()
            if mode == "format":
                # allow formatting keys {url} and {api}
                uri = SHORTLINK_API_URL.format(url=httpx.utils.quote(target_url, safe=''), api=SHORTLINK_API_KEY, key=SHORTLINK_API_KEY)
                resp = await client.get(uri)
            elif mode == "json":
                payload = {"url": target_url}
                # include key in body if provided
                if SHORTLINK_API_KEY:
                    payload["key"] = SHORTLINK_API_KEY
                resp = await client.post(SHORTLINK_API_URL, json=payload)
            else:  # default: query param GET
                params = {"url": target_url}
                if SHORTLINK_API_KEY:
                    params[SHORTLINK_API_KEY_PARAM] = SHORTLINK_API_KEY
                resp = await client.get(SHORTLINK_API_URL, params=params)

            if resp.status_code >= 400:
                log.warning("shortlink provider returned status %s: %s", resp.status_code, resp.text[:200])
                return None

            # Try to parse common response patterns:
            text = resp.text.strip()
            # common providers return direct short URL in body
            # or JSON with keys like 'short', 'shortUrl', 'result', 'data'
            try:
                j = resp.json()
            except Exception:
                j = None

            if j:
                # heuristics for short url location
                for k in ("short", "short_url", "shortUrl", "url", "result", "data"):
                    if isinstance(j, dict) and k in j:
                        val = j[k]
                        # sometimes nested
                        if isinstance(val, dict):
                            for subk in ("short", "shortUrl", "url"):
                                if subk in val:
                                    return val[subk]
                        else:
                            return val
                # fallback: flatten and search strings that look like URLs
                def find_url_in_obj(obj):
                    if isinstance(obj, str) and obj.startswith("http"):
                        return obj
                    if isinstance(obj, dict):
                        for v in obj.values():
                            res = find_url_in_obj(v)
                            if res:
                                return res
                    if isinstance(obj, list):
                        for item in obj:
                            res = find_url_in_obj(item)
                            if res:
                                return res
                    return None
                candidate = find_url_in_obj(j)
                if candidate:
                    return candidate

            # if not JSON or heuristics fail, maybe body is direct URL
            if text.startswith("http"):
                return text.splitlines()[0].strip()

            # no clear short url
            log.warning("Couldn't find short url in provider response. Response head: %s", text[:300])
            return None

        except Exception as e:
            log.exception("shortlink provider call failed: %s", e)
            return None

async def create_ad_session(user_id: int, dest_url: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create an ad session and generate a short link that will eventually redirect to
    DOMAIN/ad/callback/{token} (so that when the ad flow finishes, the provider or the ad-landing
    page should redirect there).
    Returns dict with keys: token, short_url (or None), raw_callback_url
    """
    token = uuid.uuid4().hex
    now = datetime.utcnow()
    callback = _make_callback_url(token)
    doc = {
        "token": token,
        "user_id": int(user_id),
        "created_at": now,
        "completed": False,
        "completed_at": None,
        "dest_url": dest_url,
        "callback_url": callback,
        "short_url": None,
        "meta": meta or {},
    }
    await ad_sessions.insert_one(doc)

    # Try to create a shortlink for the callback URL (so that we can hand the user a neat link).
    short = await _call_shortlink_provider(callback)
    if short:
        await ad_sessions.update_one({"token": token}, {"$set": {"short_url": short}})
        doc["short_url"] = short
    else:
        # fallback: keep callback as the link
        doc["short_url"] = callback
        await ad_sessions.update_one({"token": token}, {"$set": {"short_url": callback}})

    return {"token": token, "short_url": doc["short_url"], "callback_url": callback}

async def get_session(token: str) -> Optional[Dict[str, Any]]:
    return await ad_sessions.find_one({"token": token})

async def mark_completed(token: str) -> bool:
    res = await ad_sessions.update_one({"token": token, "completed": False}, {"$set": {"completed": True, "completed_at": datetime.utcnow()}})
    return res.modified_count > 0
