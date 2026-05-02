#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_URL="http://127.0.0.1:8000/api/status"
UI_URL="http://127.0.0.1:3000"
LOG_DIR="$ROOT/data/logs"
mkdir -p "$LOG_DIR"

require_command() {
  local name="$1"
  local hint="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "$name is not installed. $hint" >&2
    exit 1
  fi
}

wait_for_url() {
  local url="$1"
  local name="$2"
  local timeout="$3"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if python3 - "$url" >/dev/null 2>&1 <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=3) as response:
    response.read(1)
PY
    then
      echo "$name is ready: $url"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "$name did not start in $timeout seconds. Check logs in data/logs." >&2
  return 1
}

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "$UI_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$UI_URL" >/dev/null 2>&1 || true
  else
    echo "Open this address in your browser: $UI_URL"
  fi
}

cleanup() {
  if [ "${API_PID:-}" ]; then kill "$API_PID" >/dev/null 2>&1 || true; fi
  if [ "${WEB_PID:-}" ]; then kill "$WEB_PID" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT INT TERM

require_command uv "Run ./setup-unix.sh first."
require_command npm "Install Node.js LTS and run ./setup-unix.sh again."
require_command python3 "Install Python 3.11 or newer."

if [ ! -f ".env" ]; then
  cp config/settings.example.env .env
fi

echo "Starting API..."
uv run uvicorn betexplorer_scraper.api:app --host 127.0.0.1 --port 8000 >"$LOG_DIR/api-launch.out.log" 2>"$LOG_DIR/api-launch.err.log" &
API_PID=$!
wait_for_url "$API_URL" "API" 90

echo "Starting UI..."
npm --prefix apps/desktop/web run dev >"$LOG_DIR/web-launch.out.log" 2>"$LOG_DIR/web-launch.err.log" &
WEB_PID=$!
wait_for_url "$UI_URL" "UI" 90

open_browser

echo
echo "BetExplorer Monitor is running."
echo "Browser: $UI_URL"
echo "Logs: $LOG_DIR"
echo "Keep this terminal open. Press Ctrl+C to stop."

while kill -0 "$API_PID" >/dev/null 2>&1 && kill -0 "$WEB_PID" >/dev/null 2>&1; do
  sleep 2
done

echo "One of the app processes stopped. Check logs in data/logs." >&2
exit 1
