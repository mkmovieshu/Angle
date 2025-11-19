import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("MONGO_DB_NAME", "angledb")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

users = db["users"]
videos = db["videos"]
ad_sessions = db["ad_sessions"]
