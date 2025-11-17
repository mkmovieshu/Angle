# app/ads/service.py
import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env for ads.service")

DB_NAME = os.getenv("MONGO_DB_NAME", "video_bot_db")
client = MongoClient(MONGO_URL)
db = client[DB_NAME]

ad_sessions_col = db.get_collection("ad_sessions")

def mark_ad_completed(token: str) -> bool:
    """
    Mark ad session completed by token (called by your ad provider webhook).
    Returns True if session updated.
    """
    result = ad_sessions_col.update_one({"token": token}, {"$set": {"completed": True}})
    return result.matched_count == 1
