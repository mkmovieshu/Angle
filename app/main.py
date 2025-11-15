from fastapi import FastAPI
from app.routes import router
from app.admin.routes import admin_router

app = FastAPI()

app.include_router(router)
app.include_router(admin_router)

@app.get("/")
async def home():
    return {"status": "ANGEL bot backend running"}
