#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$DIR/com.p.ccclipclean.plist.template"
PLIST="$DIR/com.p.ccclipclean.plist"
DEST="$HOME/Library/LaunchAgents/com.p.ccclipclean.plist"
LABEL="com.p.ccclipclean"
CLEANER="$DIR/cleaner.py"
LOG="$DIR/cleaner.log"

PYTHON="${PYTHON:-$(command -v python3)}"
if [ -z "$PYTHON" ]; then
    echo "[cc-clipclean] ✗ python3 not found on PATH. Install Python 3 first." >&2
    exit 1
fi

echo "[cc-clipclean] using python: $PYTHON"

echo "[cc-clipclean] installing pyobjc-framework-Cocoa..."
"$PYTHON" -m pip install --quiet pyobjc-framework-Cocoa

echo "[cc-clipclean] running self-test..."
"$PYTHON" "$CLEANER" --test

echo "[cc-clipclean] generating plist from template..."
sed -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@CLEANER@|$CLEANER|g" \
    -e "s|@LOG@|$LOG|g" \
    "$TEMPLATE" > "$PLIST"

if launchctl list | grep -q "$LABEL"; then
    echo "[cc-clipclean] already loaded — unloading first..."
    launchctl unload "$DEST" 2>/dev/null || true
fi

echo "[cc-clipclean] copying plist to ~/Library/LaunchAgents/..."
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST" "$DEST"

echo "[cc-clipclean] loading launch agent..."
launchctl load "$DEST"

sleep 1
if launchctl list | grep -q "$LABEL"; then
    echo "[cc-clipclean] ✓ running. Logs: $LOG"
else
    echo "[cc-clipclean] ✗ not running — check $LOG" >&2
    exit 1
fi
