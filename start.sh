#!/bin/bash
set -e

# Start FastAPI from root main.py
uvicorn main:app --host 0.0.0.0 --port 8080 &

# Start Telegram bot by running the script file directly (no package import needed)
if [ -f "./telegram/bot.py" ]; then
  python ./telegram/bot.py &
else
  echo "No bot.py found at ./telegram/bot.py — skipping bot start."
fi

wait -n
