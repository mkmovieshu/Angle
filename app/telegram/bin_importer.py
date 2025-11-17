# app/telegram/bin_importer.py
"""
Pyrogram based importer to read channel posts (videos) from BIN channel
and store minimal metadata into MongoDB used by your bot.
"""

import os
import asyncio
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from datetime import datetime
from pymongo import MongoClient

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")  # optional, recommended to keep
BOT_TOKEN = os.getenv("BOT_TOKEN")
BIN_CHANNEL = os.getenv("BIN_CHANNEL")  # can be '@username' or '-100123...'
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI required in env")

if not (API_ID and API_HASH):
    raise RuntimeError("API_ID and API_HASH required in env for Pyrogram")

# DB setup
mongo = MongoClient(MONGO_URI)
db = mongo.get_database()  # uses default or from URI
videos_col = db.get_collection("videos")

# Pyrogram client (user session recommended). If STRING_SESSION provided, it will be used.
app = Client(
    "bin_importer_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION if STRING_SESSION else None,
    # no bot_token here — this is user client (safer to read channel posts)
)

async def import_recent(limit=50):
    """
    Import last `limit` messages from BIN_CHANNEL and store video metadata to MongoDB.
    Returns number of new videos inserted.
    """
    if not BIN_CHANNEL:
        raise RuntimeError("BIN_CHANNEL not set")

    inserted = 0
    async with app:
        try:
            async for msg in app.get_chat_history(BIN_CHANNEL, limit=limit):
                # skip if no video / animation / document
                has_video = False
                file_field = None
                ftype = None

                if msg.video:
                    has_video = True
                    file_field = msg.video
                    ftype = "video"
                elif msg.document:
                    # sometimes videos are stored as document
                    # check mime type hint
                    mime = (msg.document.mime_type or "").lower()
                    if "video" in mime or msg.document.file_name.endswith((".mp4", ".mkv", ".mov", ".3gp")):
                        has_video = True
                        file_field = msg.document
                        ftype = "document"
                elif msg.animation:
                    has_video = True
                    file_field = msg.animation
                    ftype = "animation"

                if not has_video:
                    continue

                # Basic metadata
                video_meta = {
                    "message_id": msg.message_id,
                    "chat_id": msg.chat.id,
                    "chat_username": getattr(msg.chat, "username", None),
                    "file_id": file_field.file_id,
                    "file_unique_id": file_field.file_unique_id,
                    "file_name": getattr(file_field, "file_name", None),
                    "mime_type": getattr(file_field, "mime_type", None),
                    "duration": getattr(file_field, "duration", None),
                    "width": getattr(file_field, "width", None),
                    "height": getattr(file_field, "height", None),
                    "size": getattr(file_field, "file_size", None),
                    "date": datetime.utcfromtimestamp(msg.date),
                    "caption": msg.caption or "",
                    "provider": "bin_channel_import",
                    "imported_at": datetime.utcnow()
                }

                # upsert to avoid duplicates by (chat_id, message_id)
                q = {"chat_id": video_meta["chat_id"], "message_id": video_meta["message_id"]}
                existing = videos_col.find_one(q)
                if existing:
                    # optionally update metadata if changed
                    videos_col.update_one(q, {"$set": {"imported_at": video_meta["imported_at"], "caption": video_meta["caption"]}})
                    continue

                videos_col.insert_one(video_meta)
                inserted += 1

        except FloodWait as fw:
            print("FloodWait, sleeping", fw.x)
            await asyncio.sleep(fw.x)
        except RPCError as re:
            print("Pyrogram RPCError:", re)
        except Exception as e:
            print("Unknown error in importer:", repr(e))

    return inserted

# small sync wrapper to call from normal code
def run_import(limit=50):
    return asyncio.get_event_loop().run_until_complete(import_recent(limit=limit))

if __name__ == "__main__":
    print("Importing...")
    n = run_import(100)
    print("Inserted:", n)
