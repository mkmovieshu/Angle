from app.database import users, videos
from app.telegram.keyboards import next_btn, ad_btn

async def ensure_user(uid: int):
    u = await users.find_one({"user_id": uid})
    if not u:
        u = {"user_id": uid, "sent": []}
        await users.insert_one(u)
    return u

async def send_video(app, chat_id: int, user):
    # pick first unseen
    seen = user["sent"]
    v = await videos.find_one({"file_id": {"$nin": seen}})
    if not v:
        await app.bot.send_message(chat_id, "No more videos.")
        return

    fid = v["file_id"]
    kb = next_btn()

    await app.bot.send_video(chat_id, fid, caption=v.get("caption", ""), reply_markup=kb)

    await users.update_one(
        {"user_id": user["user_id"]},
        {"$push": {"sent": fid}}
    )
