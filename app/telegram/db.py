# app/telegram/db.py
from pymongo import MongoClient
from app.config import MONGO_URL, MONGO_DB_NAME

if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

_client = MongoClient(MONGO_URL)
_db = _client[MONGO_DB_NAME]

# exported symbols
client = _client
db = _db
