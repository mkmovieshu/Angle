# app/telegram/membership.py
import logging
from typing import Optional
from app.telegram.bot import bot
from app.config import REQUIRED_GROUP_ID

log = logging.getLogger("membership")

async def is_user_member(user_id: int) -> bool:
    """
    Return True if no REQUIRED_GROUP_ID set or if user is confirmed member.
    """
    if not REQUIRED_GROUP_ID:
        return True
    try:
        cm = await bot.get_chat_member(chat_id=REQUIRED_GROUP_ID, user_id=user_id)
        if cm.status in ("creator", "administrator", "member"):
            return True
        if cm.status not in ("left", "kicked"):
            return True
        return False
    except Exception as e:
        log.exception("membership check failed for %s: %s", user_id, e)
        return False
