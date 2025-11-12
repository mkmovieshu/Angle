# Video Bank Bot

Quick start:

1. Fill `.env` with correct env vars (BOT_TOKEN, MONGO_URI, ADMIN_IDS, DOMAIN, AD_TARGET_URL).
2. Start server: `python server.py` (or deploy to Render as Web Service).
3. Start bot: `python bot.py` (or deploy to Render as Background Worker).
4. As admin, forward channel video posts to the bot to import them (use /import or just forward).
5. Users press Free Video, get 5 free; when exhausted they will be asked to watch short ad. Ad host must call `/ad/callback` with `{"token":"...","status":"completed"}` to verify.

Security notes:
- Use HTTPS for server endpoints.
- Verify ad-provider signatures if provided.
- Use short token TTL & replay protections in production.
