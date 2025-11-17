# app/ads/service.py
import os
import uuid
import time
import json
from datetime import datetime, timezone

try:
    # try to reuse existing db client in repo if present
    from app.database import db
    _db = db
except Exception:
    from pymongo import MongoClient
    MONGO_URL = os.getenv("MONGO_URL")
    if not MONGO_URL:
        raise RuntimeError("MONGO_URL env required")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    _db = client.get_default_database() or client["video_web_bot"]

ad_sessions = _db.get_collection("ad_sessions")

SHORTX_API = os.getenv("SHORTX_API")  # example provider token
DOMAIN = os.getenv("DOMAIN")  # https://yourdomain.com
AD_PROVIDER = os.getenv("AD_PROVIDER", "shortx")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def create_ad_session(user_id: int, provider: str = None, dest_url: str = None):
    """
    Create an ad session:
    - Generates token
    - Calls provider API to create short_url (if provider configured)
    - Saves session to DB with completed=False
    Returns dict with token and short_url (may be None if provider failed)
    """
    provider = provider or AD_PROVIDER
    token = uuid.uuid4().hex
    return_url = f"{DOMAIN.rstrip('/')}/ad/complete/{token}"
    doc = {
        "token": token,
        "user_id": int(user_id),
        "provider": provider,
        "short_url": None,
        "provider_payload": None,
        "dest_url": dest_url or return_url,
        "return_url": return_url,
        "completed": False,
        "created_at": _now_iso(),
    }

    # try provider: ShortX example (replace with your provider)
    if provider.lower() in ("shortx", "shortxlinks", "shortxlinks.in"):
        if not SHORTX_API:
            # provider not configured
            ad_sessions.insert_one(doc)
            return {"token": token, "short_url": None}
        try:
            import requests
            # Example ShortX API pattern (change per your provider)
            # GET https://shortxlinks.com/api?api=APIKEY&url={dest}&alias=ad{token}
            payload_url = dest_url or return_url
            api_url = f"https://shortxlinks.com/api?api={SHORTX_API}&url={payload_url}&alias=ad{token[:8]}"
            resp = requests.get(api_url, timeout=10)
            result = resp.json() if resp.text else {"status": "error", "message": "no-response"}
            doc["provider_payload"] = result
            if isinstance(result, dict) and result.get("status") in ("success",):
                short = result.get("shortenedUrl") or result.get("short_url") or result.get("shortUrl")
                doc["short_url"] = short
            else:
                # sometimes provider returns 'shortenedUrl' under different keys
                doc["short_url"] = result.get("shortenedUrl") if isinstance(result, dict) else None
        except Exception as e:
            doc["provider_payload"] = {"error": str(e)}
    else:
        # unknown provider - save doc; admin can fill short_url manually
        pass

    ad_sessions.insert_one(doc)
    return {"token": token, "short_url": doc.get("short_url"), "provider_payload": doc.get("provider_payload")}

def get_session(token: str):
    return ad_sessions.find_one({"token": token})

def mark_completed(token: str, provider_payload: dict = None):
    now = _now_iso()
    update = {"$set": {"completed": True, "completed_at": now}}
    if provider_payload:
        update["$set"]["provider_payload"] = provider_payload
    res = ad_sessions.update_one({"token": token}, update)
    return res.modified_count > 0

# helper to cleanup expired tokens (optional)
def expire_old_sessions(hours: int = 24):
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    ad_sessions.delete_many({"created_at": {"$lt": datetime.fromtimestamp(cutoff, timezone.utc).isoformat()}})
