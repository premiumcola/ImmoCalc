#!/usr/bin/env bash
# Selfcheck ohne Docker: serviert public/ und laesst den Headless-Browser-Test laufen.
# Voraussetzung einmalig:  npm install && npx playwright install chromium
set -euo pipefail
cd "$(dirname "$0")"
PORT="${CHECK_PORT:-8099}"
python3 -m http.server "$PORT" --directory public >/tmp/immocalc-check-http.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
sleep 1
BASE_URL="http://localhost:$PORT" node tests/smoke.mjs
