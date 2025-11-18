from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from app.config import BOT_TOKEN, WEBHOOK_URL
from app.telegram.handlers import start_handler, text_handler
from app.telegram.handlers_ad import ad_callback_handler
from app.telegram.video_service import video_request_handler
from app.telegram.channel_import import import_handler


async def error_handler(update, context):
    print("ERROR:", context.error)


def create_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("import", import_handler))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Callbacks (next, ads, verify, etc.)
    app.add_handler(CallbackQueryHandler(ad_callback_handler))

    # Video Requests (button click → fetch from DB)
    app.add_handler(CallbackQueryHandler(video_request_handler, pattern="^video_"))

    # Errors
    app.add_error_handler(error_handler)

    return app


app = create_app()

# Webhook Mode
app.run_webhook(
    listen="0.0.0.0",
    port=8080,
    webhook_url=f"{WEBHOOK_URL}/webhook",
)
