# app/main.py
import uvicorn
from fastapi import FastAPI
from .routes import router
from .database import ensure_indexes
import logging

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="ANGEL Video Service")
app.include_router(router)

@app.on_event("startup")
async def startup():
    await ensure_indexes()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(__import__("os").environ.get("PORT","8080")), log_level="info")
