#!/bin/bash
set -e

# Start API
uvicorn app.main:app --host 0.0.0.0 --port 8080 &

# Start telegram bot
python -m app.telegram.bot &

wait -n
