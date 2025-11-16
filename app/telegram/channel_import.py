# app/telegram/channel_import.py
import logging
from datetime import datetime
from typing import Optional

from telegram import Message

from app.database import videos  # assume this is an async motor collection
from app.config import BIN_CHANNEL, ADMIN_CHAT_ID
from app.telegram.bot import bot

log = logging.getLogger("channel_import")


def _now_iso():
    return datetime.utcnow().isoformat()


async def import_channel_post(msg: Message) -> Optional[dict]:
    """
    Import a channel_post into the videos collection.
    Returns the inserted document or None if nothing imported.
    """
    try:
        # Ensure this post belongs to the configured BIN_CHANNEL if provided
        if BIN_CHANNEL is not None:
            # msg.chat.id is the channel id
            if getattr(msg.chat, "id", None) != BIN_CHANNEL:
                log.debug("Channel post from %s ignored (not BIN_CHANNEL)", getattr(msg.chat, "id", None))
                return None

        file_id = None
        media_type = None

        # prioritize video, then animation, then document (mp4), then video_note
        if msg.video:
            file_id = msg.video.file_id
            media_type = "video"
        elif msg.animation:
            file_id = msg.animation.file_id
            media_type = "animation"
        elif msg.document:
            # check mime-type optionally
            file_id = msg.document.file_id
            media_type = "document"
        elif msg.video_note:
            file_id = msg.video_note.file_id
            media_type = "video_note"

        if not file_id:
            log.debug("Channel post has no supported media; skipping.")
            return None

        # Prevent duplicates by file_id or channel_post_id
        existing = await videos.find_one({
            "$or": [
                {"file_id": file_id},
                {"channel_post_id": msg.message_id}
            ]
        })
        if existing:
            log.info("Channel post already imported: file_id=%s post=%s", file_id, msg.message_id)
            return None

        doc = {
            "file_id": file_id,
            "type": media_type,
            "caption": msg.caption or "",
            "from_channel_id": getattr(msg.chat, "id", None),
            "channel_title": getattr(msg.chat, "title", None),
            "channel_post_id": msg.message_id,
            "created_at": _now_iso(),
        }

        res = await videos.insert_one(doc)
        log.info("Imported new video doc_id=%s file_id=%s", getattr(res, "inserted_id", None), file_id)

        # notify admin optionally
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Imported video from channel {doc['channel_title'] or doc['from_channel_id']}: file_id={file_id}")
            except Exception:
                log.exception("Failed to notify admin about import")

        return doc

    except Exception as e:
        log.exception("Failed importing channel post: %s", e)
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(ADMIN_CHAT_ID, f"Error importing channel post: {e}")
            except Exception:
                pass
        return None
