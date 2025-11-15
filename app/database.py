from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGO_URL

client = AsyncIOMotorClient(MONGO_URL)
db = client["angel"]

users = db["users"]
videos = db["videos"]
ad_sessions = db["ad_sessions"]
