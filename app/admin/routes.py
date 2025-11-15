from fastapi import APIRouter
from app.database import videos

admin_router = APIRouter(prefix="/admin")

@admin_router.post("/add_video")
async def add_video(file_id: str):
    await videos.insert_one({"file_id": file_id})
    return {"status": "added"}
