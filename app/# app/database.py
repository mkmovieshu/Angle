# app/database.py
import motor.motor_asyncio
from .config import MONGO_URI, DB_NAME
import logging

log = logging.getLogger("video-web.db")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# collections
users_col = db["users"]
videos_col = db["videos"]
ad_col = db["ad_sessions"]

async def ensure_indexes():
    try:
        await videos_col.create_index([("file_id",1)], unique=False)
        await videos_col.create_index([("channel_id",1),("message_id",1)], unique=True, sparse=True)
        await users_col.create_index([("user_id",1)], unique=True)
        await ad_col.create_index([("token",1)], unique=True)
    except Exception:
        log.exception("ensure_indexes failed")
