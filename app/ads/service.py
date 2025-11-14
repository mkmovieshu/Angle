# app/ads/service.py
# lightweight ad utilities (we used create_ad_session above)
from ..database import ad_col
from datetime import datetime
def now():
    return datetime.utcnow()

async def complete_token(token:str):
    res = await ad_col.update_one({"token":token,"status":"pending"},{"$set":{"status":"completed","completed_at":now()}})
    return res.modified_count > 0
