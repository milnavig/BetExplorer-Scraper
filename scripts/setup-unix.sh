#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

require_command() {
  local name="$1"
  local hint="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "$name is not installed. $hint" >&2
    exit 1
  fi
}

run_step() {
  local title="$1"
  shift
  echo
  echo "==> $title"
  "$@"
}

echo "BetExplorer Monitor setup"
echo "Project folder: $ROOT"

require_command python3 "Install Python 3.11 or newer."
require_command npm "Install Node.js LTS from https://nodejs.org/."

if ! command -v uv >/dev/null 2>&1; then
  run_step "Installing uv" python3 -m pip install --user uv
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -f ".env" ]; then
  cp config/settings.example.env .env
  echo "Created .env from config/settings.example.env"
fi

run_step "Creating Python environment" uv venv .venv
run_step "Installing Python dependencies" uv pip install -e "."
run_step "Installing UI dependencies" npm --prefix apps/desktop/web install

echo
echo "Setup completed. Use ./start-unix.sh or the desktop shortcut to run the app."
