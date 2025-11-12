
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
DB_NAME = os.getenv('DB_NAME', 'video_bot_db')

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
users = db['users']
videos = db['videos']
ad_sessions = db['ad_sessions']
