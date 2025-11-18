# app/routes.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import asyncio

logger = logging.getLogger("app.routes")

router = APIRouter()


@router.get("/")
async def root():
    return {"ok": True, "message": "Service is up"}


@router.post("/webhook")
async def webhook(request: Request):
    """
    Telegram will POST updates here.
    We import the handler lazily to avoid circular imports during startup.
    The handler (handle_update) should accept the parsed JSON dict and may be
    either a coroutine or a normal function.
    """
    try:
        data = await request.json()
    except Exception as e:
        logger.exception("Failed to parse JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Defensive: ensure we return quickly with 200 for healthy but handle errors internally.
    try:
        # lazy import to avoid circular import issues
        try:
            from app.telegram.handlers import handle_update
        except Exception as imp_e:
            logger.exception("Could not import app.telegram.handlers.handle_update")
            # Raise a clear error so logs show precise failure
            raise RuntimeError(f"handle_update not available: {imp_e}") from imp_e

        # call the handler; support both async and sync handlers
        result = handle_update(data)
        if asyncio.iscoroutine(result):
            await result

        # success
        return JSONResponse({"ok": True})

    except Exception as e:
        # log full stacktrace so you can paste it here if something goes wrong
        logger.exception("Error while handling update: %s", e)
        # include the exception message in response so Render logs show it
        raise HTTPException(status_code=500, detail=f"Error while handling update: {e}")
# inside your app/routes.py (add this endpoint)
from fastapi import Request, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from app.telegram.handlers import ad_sessions_col, users_col  # or import db and collections
import logging

logger = logging.getLogger(__name__)

@router.get("/ad/return")
async def ad_return(token: str, uid: str = None):
    """
    Advertiser / shortener should redirect users here after they 'watched' ad.
    We mark the ad_session.completed True.
    Optionally, you can automatically refill user free_remaining here.
    """
    session = ad_sessions_col.find_one({"token": token})
    if not session:
        logger.warning("ad/return called with invalid token %s", token)
        # still redirect to a friendly page
        return PlainTextResponse("Invalid token", status_code=400)
    # mark completed
    ad_sessions_col.update_one({"token": token}, {"$set": {"completed": True, "completed_at": int(time.time())}})
    # optionally refill user immediately (or wait for user to press 'I watched' in bot)
    try:
        uid_int = int(uid) if uid else session.get("user_id")
        users_col.update_one({"user_id": uid_int}, {"$set": {"free_remaining": FREE_LIMIT, "cursor": 0}})
    except Exception:
        logger.exception("Failed to refill user after ad return")
    # you can show a small page, or redirect back to Telegram deep link or thankyou page
    # Redirect to a simple thank-you page on your domain (or a landing)
    return PlainTextResponse("Thanks — ad completion recorded. Return to Telegram and press 'I watched'.")
