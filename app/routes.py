# app/routes.py
import logging
import sys
import traceback
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from app.telegram.handlers import handle_update  # ensure this exists
from app.config import DOMAIN

logger = logging.getLogger("uvicorn.error")

app = FastAPI()

@app.get("/")
async def root():
    return {"ok": True, "message": "ANGEL service is alive."}

@app.post("/webhook")
async def webhook(request: Request):
    """
    Telegram will POST updates here.
    We parse JSON and forward to handle_update(data).
    Always return a 200 to Telegram unless something fatal happens.
    """
    try:
        data = await request.json()
    except Exception as exc:
        logger.exception("Invalid JSON received on /webhook")
        # Bad request from client
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Defensive: ensure handle_update is present and callable
    if not callable(handle_update):
        msg = "handle_update not available or not callable."
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)

    # Call handler and catch errors so Telegram gets 200 (or controlled 500)
    try:
        await handle_update(data)
    except Exception as exc:
        # Log full traceback for debugging
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error("Error while handling update: %s\n%s", exc, tb)

        # Return 200 to Telegram if you want to ack (so it won't retry endlessly).
        # But return 500 if you prefer Telegram to retry. We'll return 500 so you see the error in logs.
        # If you want Telegram to stop retries, change status_code to 200.
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    # success
    return JSONResponse(status_code=200, content={"ok": True})
