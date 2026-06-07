#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# --- Preflight checks ---
if ! command -v conda &>/dev/null; then
  echo "Error: conda not found. Make sure conda is initialised in your shell." >&2
  exit 1
fi

if ! conda env list | grep -q "^ytframes "; then
  echo "Error: conda env 'ytframes' not found. See README.md for setup." >&2
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo "Error: npm not found." >&2
  exit 1
fi

# --- Kill both servers when the script exits (Ctrl+C or error) ---
cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "Done."
}
trap cleanup INT TERM EXIT

# --- Start backend ---
echo "▶ Starting backend (ytframes env)..."
cd "$ROOT/backend"
conda run --no-capture-output -n ytframes \
  uvicorn main:app --port 8000 &
BACKEND_PID=$!

# --- Start frontend ---
echo "▶ Starting frontend..."
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

# --- Wait until both ports respond (up to 15 s) ---
echo "  Waiting for servers..."
for _ in $(seq 1 30); do
  backend_up=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs 2>/dev/null || true)
  frontend_up=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || true)
  if [ "$backend_up" = "200" ] && [ "$frontend_up" = "200" ]; then
    break
  fi
  sleep 0.5
done

echo ""
echo "  ✓ YT Frame Extractor is running"
echo "    Frontend → http://localhost:5173"
echo "    Backend  → http://localhost:8000"
echo "    Press Ctrl+C to stop both servers."
echo ""

open http://localhost:5173

# Keep running until Ctrl+C
wait
