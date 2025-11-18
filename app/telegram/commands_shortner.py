# app/telegram/commands_shortner.py
import asyncio
import requests
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# these helpers must exist in your project (as in your repo)
# silicondb.get_bot_sttgs(), save_group_settings(grp_id, key, value), is_check_admin(...)
from app.telegram.helpers import silicondb, save_group_settings, is_check_admin  # adjust import path if needed
from app.config import (
    # fallback defaults used in exception handling
    SHORTLINK_API_KEY,
    SHORTLINK_API_URL,
)
from app.config import get_logger

logger = get_logger(__name__)

# replace LOG_API_CHANNEL with your project notifier channel id (or getenv)
LOG_API_CHANNEL = "me"  # change to your admin channel id or keep as "me" or chat id

# default values (if any) - these names expected by save_group_settings fallback in original snippet
SHORTENER_WEBSITE = SHORTLINK_API_URL or "https://shortxlinks.com"
SHORTENER_API = SHORTLINK_API_KEY or ""

# set_shortner command
@Client.on_message(filters.command('set_shortner'))
async def set_shortner(c: Client, m: Message):
    sili = silicondb.get_bot_sttgs()

    if sili and sili.get('MAINTENANCE_MODE', False):
        return await m.reply_text(
            "<b>⚙️ ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ!\n\n"
            "🚧 ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.</b>"
        )
    grp_id = m.chat.id
    chat_type = m.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await m.reply_text("<b>ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    if not await is_check_admin(c, grp_id, m.from_user.id):
        return await m.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    if len(m.text.split()) == 1:
        await m.reply("<b>Use this command like this - \n\n`/set_shortner tnshort.net 06b24eb6bbb025713cd522fb3f696b6d5de11354`</b>")
        return
    sts = await m.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    await asyncio.sleep(1.2)
    await sts.delete()
    try:
        URL = m.command[1]
        API = m.command[2]
        # attempt simple verify call (as original)
        resp = requests.get(f'https://{URL}/api?api={API}&url=https://telegram.dog/bisal_files', timeout=8).json()
        SHORT_LINK = None
        if isinstance(resp, dict) and resp.get('status') == 'success':
            SHORT_LINK = resp.get('shortenedUrl') or resp.get('short') or resp.get('data')
        await save_group_settings(grp_id, 'shortner', URL)
        await save_group_settings(grp_id, 'api', API)
        reply_text = f"<b><u>✓ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʏᴏᴜʀ sʜᴏʀᴛɴᴇʀ ɪs ᴀᴅᴅᴇᴅ</u>\n\n"
        if SHORT_LINK:
            reply_text += f"ᴅᴇᴍᴏ - {SHORT_LINK}\n\n"
        reply_text += f"sɪᴛᴇ - `{URL}`\n\nᴀᴘɪ - `{API}`</b>"
        await m.reply_text(reply_text, quote=True)
        user_id = m.from_user.id
        user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
        try:
            link = (await c.get_chat(m.chat.id)).invite_link
        except Exception:
            link = ""
        grp_link = f"[{m.chat.title}]({link})" if link else m.chat.title
        log_message = f"#New_Shortner_Set_For_1st_Verify\n\nName - {user_info}\nId - `{user_id}`\n\nDomain name - {URL}\nApi - `{API}`\nGroup link - {grp_link}"
        try:
            await c.send_message(LOG_API_CHANNEL, log_message, disable_web_page_preview=True)
        except Exception:
            logger.info("LOG channel send failed; LOG_API_CHANNEL=%s", LOG_API_CHANNEL)
    except Exception as e:
        await save_group_settings(grp_id, 'shortner', SHORTENER_WEBSITE)
        await save_group_settings(grp_id, 'api', SHORTENER_API)
        await m.reply_text(f"<b><u>💢 ᴇʀʀᴏʀ ᴏᴄᴄᴏᴜʀᴇᴅ!!</u>\n\nᴀᴜᴛᴏ ᴀᴅᴅᴇᴅ ʙᴏᴛ ᴏᴡɴᴇʀ ᴅᴇꜰᴜʟᴛ sʜᴏʀᴛɴᴇʀ\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇɴ ᴜsᴇ ᴄᴏʀʀᴇᴄᴛ ꜰᴏʀᴍᴀᴛ ᴏʀ ᴀᴅᴅ ᴠᴀʟɪᴅ sʜᴏʀᴛɴᴇʀ ᴅᴏᴍᴀɪɴ ɴᴀᴍᴇ & ᴀᴘɪ\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>", quote=True)
