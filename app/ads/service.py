import uuid
import aiohttp
import urllib.parse
from datetime import datetime
from app.database import ad_sessions
from app.config import SHORTX_API_KEY, DOMAIN

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

    await ad_sessions.insert_one({
        "token": token,
        "user_id": user_id,
        "status": "pending",
        "redirect_url": None,
        "created_at": utcnow(),
        "completed_at": None
    })

    async with aiohttp.ClientSession() as s:
        async with s.get(short_api) as r:
            js = await r.json()
            short_url = js.get("shortenedUrl") or js.get("short_url") or js

            await ad_sessions.update_one(
                {"token": token},
                {"$set": {"redirect_url": short_url}}
            )

            return token, short_url


async def mark_ad_completed(token: str):
    await ad_sessions.update_one(
        {"token": token},
        {"$set": {"status": "completed", "completed_at": utcnow()}}
    )
