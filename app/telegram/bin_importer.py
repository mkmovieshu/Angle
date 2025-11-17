import os
import asyncio
from datetime import datetime
from pymongo import MongoClient
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

BIN_CHANNEL = os.getenv("BIN_CHANNEL")

MONGO_URL = os.getenv("MONGO_URL")   # UPDATED
if not MONGO_URL:
    raise RuntimeError("MONGO_URL required in env")

mongo = MongoClient(MONGO_URL)
db = mongo.get_database()
videos_col = db.get_collection("videos")


app = Client(
    "bin_importer_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION if STRING_SESSION else None,
)


async def import_recent(limit=50):
    if not BIN_CHANNEL:
        raise RuntimeError("BIN_CHANNEL not found")

    inserted = 0

    async with app:
        try:
            async for msg in app.get_chat_history(BIN_CHANNEL, limit=limit):
                file = None
                if msg.video:
                    file = msg.video
                elif msg.document:
                    mime = (msg.document.mime_type or "").lower()
                    if "video" in mime:
                        file = msg.document

                if not file:
                    continue

                data = {
                    "message_id": msg.message_id,
                    "chat_id": msg.chat.id,
                    "file_id": file.file_id,
                    "unique_id": file.file_unique_id,
                    "caption": msg.caption or "",
                    "imported_at": datetime.utcnow(),
                }

                q = {"chat_id": data["chat_id"], "message_id": data["message_id"]}
                if videos_col.find_one(q):
                    continue

                videos_col.insert_one(data)
                inserted += 1

        except FloodWait as e:
            await asyncio.sleep(e.value)

        except RPCError as e:
            print("RPC Error:", e)

        except Exception as e:
            print("Importer error:", e)

    return inserted


def run_import(limit=50):
    return asyncio.get_event_loop().run_until_complete(import_recent(limit=limit))


if __name__ == "__main__":
    print("Importing…")
    print("Inserted:", run_import(100))
