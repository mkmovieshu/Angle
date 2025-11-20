# main.py
from fastapi import FastAPI
from web.ad_routes import router as ad_router

app = FastAPI()

@app.get("/")
async def home():
    return {"status": "ok", "service": "Angle API"}

app.include_router(ad_router)
