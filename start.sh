#!/usr/bin/env bash
# start.sh - Launch web app (uvicorn) and bot process in same container.
# Note: running both in same container is convenient; for scale, run them as separate services.

set -euo pipefail

# Optional: allow override of UVICORN module/path via env
UVICORN_MODULE=${UVICORN_MODULE:-"app.main:app"}
UVICORN_HOST=${UVICORN_HOST:-"0.0.0.0"}
UVICORN_PORT=${UVICORN_PORT:-"8080"}
UVICORN_WORKERS=${UVICORN_WORKERS:-"1"}

# Start uvicorn in background (log to file)
echo "Starting uvicorn for ${UVICORN_MODULE} on ${UVICORN_HOST}:${UVICORN_PORT}..."
uvicorn "$UVICORN_MODULE" --host "$UVICORN_HOST" --port "$UVICORN_PORT" --workers "$UVICORN_WORKERS" --log-level info &

UVICORN_PID=$!

# Wait a little for the web server to start
sleep 1

# Start the telegram bot in background (if the module exists)
# The bot entrypoint should be an async runner (e.g., python -m app.telegram.bot)
if python -c "import importlib,sys; \
             \
             sys.path.insert(0,'.'); \
             import importlib.util, pkgutil; \
             \
             \
             print('checking', end='')" 2>/dev/null; then
    if [ -f "./app/telegram/bot.py" ]; then
        echo "Starting telegram bot..."
        # run the bot as a separate process
        python -m app.telegram.bot &
        BOT_PID=$!
    else
        echo "No bot.py found at ./app/telegram/bot.py — skipping bot start."
        BOT_PID=""
    fi
else
    echo "Python path problem when checking bot module; skipping bot start."
    BOT_PID=""
fi

# Forward signals to children
_term() {
  echo "Caught SIGTERM, shutting down..."
  if [ -n "${BOT_PID:-}" ]; then kill -TERM "$BOT_PID" 2>/dev/null || true; fi
  if [ -n "${UVICORN_PID:-}" ]; then kill -TERM "$UVICORN_PID" 2>/dev/null || true; fi
  wait
  exit 0
}

trap _term SIGTERM SIGINT

# Wait on background jobs to exit
wait -n
# If any process exits, stop the rest and exit with that code
EXIT_CODE=$?
echo "A process exited with code ${EXIT_CODE}. Shutting down."
if [ -n "${BOT_PID:-}" ]; then kill -TERM "$BOT_PID" 2>/dev/null || true; fi
if [ -n "${UVICORN_PID:-}" ]; then kill -TERM "$UVICORN_PID" 2>/dev/null || true; fi
wait
exit $EXIT_CODE
