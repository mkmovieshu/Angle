# app/routes.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()

# try import the project's telegram update handler (adjust name if your repo uses different)
try:
    from app.telegram.handlers import handle_update  # must exist in your handlers.py
except Exception as e:
    logger.exception("Could not import handle_update from app.telegram.handlers: %s", e)
    # create a fallback stub so import of this module doesn't fail; will raise at runtime if used
    async def handle_update(data):
        raise RuntimeError("handle_update not available: " + str(e))

@router.get("/", response_class=PlainTextResponse)
async def root():
    return "ANGEL service ok"

@router.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"

@router.post("/webhook")
async def webhook(request: Request):
    """
    Endpoint for Telegram webhook.
    Forwards the parsed JSON body to `handle_update`.
    """
    try:
        data = await request.json()
    except Exception:
        # If body isn't JSON, return 400
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # handle_update may be sync or async; support both
    try:
        if asyncio.iscoroutinefunction(handle_update):
            await handle_update(data)
        else:
            # run sync function in threadpool to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, handle_update, data)
    except Exception as ex:
        # log full exception and return 500 so Telegram sees an error (useful for debugging)
        logger.exception("Error while handling update: %s", ex)
        # return 200 if you want Telegram to stop retrying; for debugging keep 500.
        # Here we return 500 so you see the error in logs during development.
        return JSONResponse(status_code=500, content={"ok": False, "error": str(ex)})

    return JSONResponse(content={"ok": True})
