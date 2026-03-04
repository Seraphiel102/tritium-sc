#!/usr/bin/env bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
# TRITIUM-SC Regular Mode Launcher
# Starts the server (if not running), waits for readiness, and opens
# the Command Center in a browser.
#
# Usage:
#   ./scripts/tritium-launch.sh          # start server + open browser
#   ./scripts/tritium-launch.sh 9000     # custom port

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PORT=${1:-8000}
VENV="$DIR/.venv/bin/python3"
URL="http://localhost:$PORT"
HEALTH="$URL/api/amy/status"
WE_STARTED=0

if [ ! -f "$VENV" ]; then
    echo "ERROR: Virtual environment not found at $DIR/.venv"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Check if server is already running
if curl -sf "$HEALTH" > /dev/null 2>&1; then
    echo "[TRITIUM] Server already running on port $PORT"
else
    echo "[TRITIUM] Starting server on port $PORT..."
    export CUDA_VISIBLE_DEVICES=""
    export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    "$DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" &
    SERVER_PID=$!
    WE_STARTED=1

    # Wait up to 15s for server readiness
    TRIES=30
    while [ $TRIES -gt 0 ]; do
        if curl -sf "$HEALTH" > /dev/null 2>&1; then
            echo "[TRITIUM] Server ready"
            break
        fi
        sleep 0.5
        TRIES=$((TRIES - 1))
    done

    if [ $TRIES -eq 0 ]; then
        echo "[TRITIUM] ERROR: Server did not become ready within 15s"
        kill "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
fi

# Open Command Center in default browser
echo "[TRITIUM] Opening $URL"
xdg-open "$URL" 2>/dev/null &

# If we started the server, keep process alive (taskbar icon stays)
if [ $WE_STARTED -eq 1 ]; then
    wait "$SERVER_PID"
fi
