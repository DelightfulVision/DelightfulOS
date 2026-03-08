#!/usr/bin/env bash
# DelightfulOS Demo Runner
# Starts the server, launches 2 simulators, and opens the dashboard.
# Usage: bash scripts/demo.sh

set -e

SERVER_DIR="$(cd "$(dirname "$0")/../server" && pwd)"
BASE_URL="http://127.0.0.1:8000"

cleanup() {
  echo ""
  echo "Shutting down simulators..."
  curl -s -X DELETE "$BASE_URL/system/simulate/alice" > /dev/null 2>&1 || true
  curl -s -X DELETE "$BASE_URL/system/simulate/bob"   > /dev/null 2>&1 || true
  echo "Stopping server..."
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  echo "Done."
}

trap cleanup EXIT INT TERM

echo "=== DelightfulOS Demo ==="
echo ""

# Start the server
echo "[1/4] Starting server..."
cd "$SERVER_DIR"
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

# Wait for the server to be ready
echo -n "      Waiting for server"
for i in $(seq 1 30); do
  if curl -s "$BASE_URL/health" > /dev/null 2>&1; then
    echo " ready!"
    break
  fi
  echo -n "."
  sleep 0.5
done

# Launch simulators
echo "[2/4] Starting simulator: alice"
curl -s -X POST "$BASE_URL/system/simulate/alice" | python -m json.tool 2>/dev/null || true

echo "[3/4] Starting simulator: bob"
curl -s -X POST "$BASE_URL/system/simulate/bob" | python -m json.tool 2>/dev/null || true

# Open dashboard
echo "[4/4] Opening dashboard..."
DASHBOARD_URL="$BASE_URL/dashboard"
if command -v xdg-open &> /dev/null; then
  xdg-open "$DASHBOARD_URL"
elif command -v open &> /dev/null; then
  open "$DASHBOARD_URL"
elif command -v start &> /dev/null; then
  start "$DASHBOARD_URL"
else
  echo "      Open manually: $DASHBOARD_URL"
fi

echo ""
echo "=== Demo running ==="
echo "  Dashboard: $DASHBOARD_URL"
echo "  API docs:  $BASE_URL/docs"
echo "  Users:     alice, bob (simulated)"
echo ""
echo "Press Ctrl+C to stop."
echo ""

wait "$SERVER_PID"
