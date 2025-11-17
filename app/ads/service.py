# app/ads/service.py
import os
import uuid
from datetime import datetime, timezone

# try reuse project's db if exists
try:
    from app.database import db
    _db = db
except Exception:
    from pymongo import MongoClient
    MONGO_URL = os.getenv("MONGO_URL")
    if not MONGO_URL:
        raise RuntimeError("MONGO_URL env required")
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    # if database name is in the URL, get_default_database() returns it, else fallback
    _db = client.get_default_database() or client["video_web_bot"]

ad_sessions = _db.get_collection("ad_sessions")

SHORTX_API = os.getenv("SHORTX_API")  # shortener API token (optional)
DOMAIN = os.getenv("DOMAIN", "").rstrip("/")  # e.g. https://angle-jldx.onrender.com
AD_PROVIDER = os.getenv("AD_PROVIDER", "shortx")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def create_ad_session(user_id: int, provider: str = None, dest_url: str = None):
    """
    Create an ad session document and (if possible) create a short link with provider.
    Returns a dict: { token, short_url, provider_payload }
    """
    provider = provider or AD_PROVIDER
    token = uuid.uuid4().hex
    return_url = f"{DOMAIN}/ad/complete/{token}" if DOMAIN else (dest_url or f"ad://{token}")
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
        "completed_at": None,
    }

    # If using ShortX-like provider, attempt to create short link
    if provider and provider.lower() in ("shortx", "shortxlinks", "shortxlinks.in"):
        if not SHORTX_API:
            doc["provider_payload"] = {"warning": "SHORTX_API not configured"}
        else:
            try:
                import requests
                payload_url = doc["dest_url"]
                alias = f"ad{token[:8]}"
                api_url = f"https://shortxlinks.com/api?api={SHORTX_API}&url={payload_url}&alias={alias}"
                resp = requests.get(api_url, timeout=15)
                # try parse json, else fallback to text
                try:
                    result = resp.json()
                except Exception:
                    result = {"status": "error", "raw": resp.text}
                doc["provider_payload"] = result
                # provider success keys may vary
                short = None
                if isinstance(result, dict):
                    short = result.get("shortenedUrl") or result.get("short_url") or result.get("shortUrl") or result.get("shortened")
                    # some providers return 'status' == 'success'
                    if result.get("status") in ("success", True) and not short:
                        # look for any url-like value
                        for v in result.values():
                            if isinstance(v, str) and v.startswith("http"):
                                short = v
                                break
                doc["short_url"] = short
            except Exception as e:
                doc["provider_payload"] = {"error": str(e)}
    else:
        # provider not recognized or not configured — keep doc for manual handling
        pass

    ad_sessions.insert_one(doc)
    return {"token": token, "short_url": doc.get("short_url"), "provider_payload": doc.get("provider_payload")}

def get_session(token: str):
    return ad_sessions.find_one({"token": token})

def mark_completed(token: str, provider_payload: dict = None):
    """
    Mark the ad session as completed. Returns True if modified.
    """
    now = _now_iso()
    update = {"$set": {"completed": True, "completed_at": now}}
    if provider_payload:
        update["$set"]["provider_payload"] = provider_payload
    res = ad_sessions.update_one({"token": token}, update)
    return res.modified_count > 0

# BACKWARDS-COMPATIBILITY ALIAS
# Some other modules expect mark_ad_completed; keep both names.
def mark_ad_completed(token: str, provider_payload: dict = None):
    return mark_completed(token, provider_payload)

# optional helpers
def expire_old_sessions(hours: int = 24):
    """
    Delete sessions older than `hours`. Use with care.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    # created_at stored as ISO string; to keep this simple we won't implement time-based deletion here.
    # Implement as needed using datetime comparisons.
    return
