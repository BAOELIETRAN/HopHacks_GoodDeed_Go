#!/usr/bin/env bash
# Start the GoodDeed Go stack locally.
#
#   ./run.sh           backend :8000 + frontend :5173
#   ./run.sh --seed    wipe and reseed the demo data first
#
# Ctrl+C stops both.

set -euo pipefail
cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_PORT=5173

if [ ! -f .env ]; then
  echo "!  No .env found. Copy .env.example to .env and add your keys,"
  echo "   or the app will run on stub data."
fi

free_port() {
  local pid
  pid=$(lsof -ti tcp:"$1" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "   port $1 was busy (pid $pid) -- stopping it"
    kill "$pid" 2>/dev/null || true
    sleep 1
  fi
}

echo "-> freeing ports"
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

if [ "${1:-}" = "--seed" ]; then
  echo "-> seeding demo data"
  python3 scripts/seed_demo.py
fi

echo "-> starting backend on :$BACKEND_PORT"
python3 -m uvicorn backend.main:app --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

echo "-> starting frontend on :$FRONTEND_PORT"
(cd frontend && python3 -m http.server "$FRONTEND_PORT" >/dev/null 2>&1) &
FRONTEND_PID=$!

cleanup() {
  echo
  echo "-> stopping"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for the backend to answer before announcing the URL.
for _ in $(seq 1 30); do
  if curl -fsS "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

cat <<EOF

  GoodDeed Go is running
  ----------------------
  App       http://localhost:$FRONTEND_PORT
  API docs  http://localhost:$BACKEND_PORT/docs

  Demo login   lena@demo.dev / demo1234   (run with --seed if that fails)

  Ctrl+C to stop both.

EOF

wait
