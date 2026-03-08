#!/usr/bin/env bash
# DelightfulOS ngrok tunnel
# Exposes the local server so devices on MIT WiFi can connect.
# Usage: bash scripts/tunnel.sh [port]
#
# Prereq: install ngrok (https://ngrok.com/download) and run `ngrok config add-authtoken <token>`

set -e

PORT="${1:-8000}"

if ! command -v ngrok &> /dev/null; then
  echo "Error: ngrok not found. Install it:"
  echo "  brew install ngrok   (macOS)"
  echo "  choco install ngrok  (Windows)"
  echo "  snap install ngrok   (Linux)"
  echo "  or: https://ngrok.com/download"
  exit 1
fi

echo "=== DelightfulOS Tunnel ==="
echo "Exposing localhost:$PORT via ngrok..."
echo ""
echo "Once running, update your collar firmware with the ngrok URL:"
echo '  SERVER:<ngrok-host>:443'
echo ""
echo "The Spectacles Lens should connect to:"
echo '  wss://<ngrok-host>/system/glasses/ws/{user_id}'
echo ""

ngrok http "$PORT" --log stdout
