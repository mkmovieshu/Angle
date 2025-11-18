# app/telegram/bin_importer.py
"""
Bin importer: import videos from a 'bin' channel / bin group into DB.
This module expects MONGO_URL env var (not MONGO_URI).
"""

import os
import logging
from pymongo import MongoClient
from app.config import MONGO_URL, MONGO_DB_NAME, VIDEO_COLLECTION_NAME

logger = logging.getLogger(__name__)

if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

# initialize client
client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]
videos_col = db[VIDEO_COLLECTION_NAME]

def run_import():
    """
    Placeholder: real importer will forward/scan bin channel messages and insert into videos_col.
    The original project probably uses Telegram API to forward messages; keep that logic here.
    This function is intentionally minimal so you replace with your import logic.
    """
    logger.info("run_import started")
    # Example: check latest messages placeholder
    # actual implementation depends on your logic: you likely fetch messages via bot and store tg file_id
    return True
