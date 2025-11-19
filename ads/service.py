import os
import uuid
from datetime import datetime
import httpx
from app.database import ad_sessions

DOMAIN = os.getenv("DOMAIN", "").rstrip("/")
SHORTLINK_API_URL = os.getenv("SHORTLINK_API_URL", "")
SHORTLINK_API_KEY = os.getenv("SHORTLINK_API_KEY", "")

def callback_url(token: str):
    return f"{DOMAIN}/ad/callback/{token}"

async def create_ad_session(user_id: int):
    token = uuid.uuid4().hex
    cb = callback_url(token)

    doc = {
        "token": token,
        "user_id": user_id,
        "callback_url": cb,
        "short_url": None,
        "completed": False,
        "created_at": datetime.utcnow(),
    }
    await ad_sessions.insert_one(doc)

    # Generate shortlink (optional)
    if SHORTLINK_API_URL:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(SHORTLINK_API_URL, params={"api": SHORTLINK_API_KEY, "url": cb})
                if r.status_code == 200 and "http" in r.text:
                    short = r.text.strip()
                    await ad_sessions.update_one({"token": token}, {"$set": {"short_url": short}})
                    doc["short_url"] = short
        except:
            pass

    return doc

async def get_session(token: str):
    return await ad_sessions.find_one({"token": token})

async def mark_completed(token: str):
    await ad_sessions.update_one(
        {"token": token},
        {"$set": {"completed": True, "completed_at": datetime.utcnow()}}
    )
