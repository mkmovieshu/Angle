# app/admin/routes.py
from fastapi import APIRouter, HTTPException
from ..database import videos_col, users_col
from ..config import ADMIN_IDS

router = APIRouter(prefix="/admin")

def check_admin(admin_id:int):
    return admin_id in ADMIN_IDS

@router.get("/list_videos")
async def list_videos(admin_id:int):
    if not check_admin(admin_id):
        raise HTTPException(403, "forbidden")
    docs = await videos_col.find().sort("created_at",-1).to_list(length=200)
    return {"count": len(docs), "videos": [{"file_id":d.get("file_id"), "caption":d.get("caption"), "channel_id":d.get("channel_id")} for d in docs]}

@router.post("/grant_premium")
async def grant_premium(admin_id:int, user_id:int, days:int):
    if not check_admin(admin_id):
        raise HTTPException(403, "forbidden")
    from datetime import datetime, timedelta
    user = await users_col.find_one({"user_id":user_id})
    if not user:
        await users_col.insert_one({"user_id":user_id, "created_at":datetime.utcnow(), "sent_file_ids":[]})
    until = datetime.utcnow() + timedelta(days=days)
    await users_col.update_one({"user_id":user_id},{"$set":{"premium_until": until.isoformat()}})
    return {"ok":True, "user_id": user_id, "premium_until": until.isoformat()}
