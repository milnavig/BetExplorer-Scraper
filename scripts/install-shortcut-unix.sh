#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START_SCRIPT="$ROOT/start-unix.sh"
ICON_PATH="$ROOT/apps/desktop/src-tauri/icons/icon.ico"

if [ "$(uname -s)" = "Darwin" ]; then
  DESKTOP="$HOME/Desktop"
  SHORTCUT="$DESKTOP/BetExplorer Monitor.command"
  mkdir -p "$DESKTOP"
  cat >"$SHORTCUT" <<EOF
#!/usr/bin/env bash
cd "$ROOT"
bash "$START_SCRIPT"
EOF
  chmod +x "$SHORTCUT"
  echo "Created macOS desktop launcher: $SHORTCUT"
else
  DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
  SHORTCUT="$DESKTOP/BetExplorer Monitor.desktop"
  mkdir -p "$DESKTOP"
  cat >"$SHORTCUT" <<EOF
[Desktop Entry]
Type=Application
Name=BetExplorer Monitor
Comment=Start BetExplorer Monitor
Exec=bash "$START_SCRIPT"
Path=$ROOT
Terminal=true
Icon=$ICON_PATH
Categories=Utility;
EOF
  chmod +x "$SHORTCUT"
  echo "Created Linux desktop launcher: $SHORTCUT"
fi
