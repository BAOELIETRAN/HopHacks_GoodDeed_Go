#!/usr/bin/env bash
# Start GoodDeed Go locally. One server on :8000 serves both the API and the
# frontend -- the same arrangement as the deployed Render service, so local
# and production behave identically.
#
#   ./run.sh           start
#   ./run.sh --seed    wipe and reseed the demo data first (see scripts/seed_demo.py)
#
# Ctrl+C stops it.

set -euo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8000}

if [ ! -f .env ]; then
  echo "!  No .env found. Copy .env.example to .env and add your keys,"
  echo "   or the app will run on stub data."
fi

pid=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [ -n "$pid" ]; then
  echo "-> port $PORT was busy (pid $pid), stopping it"
  kill "$pid" 2>/dev/null || true
  sleep 1
fi

if [ "${1:-}" = "--seed" ]; then
  echo "-> seeding demo data"
  python3 scripts/seed_demo.py
fi

echo "-> starting on :$PORT"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --reload &
SERVER_PID=$!
trap 'echo; echo "-> stopping"; kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 40); do
  curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1 && break
  sleep 0.5
done

cat <<EOF

  GoodDeed Go is running
  ----------------------
  App        http://localhost:$PORT
  API docs   http://localhost:$PORT/docs

  Demo logins: lena@demo.dev (Gold), ana@demo.dev (Silver), sam@demo.dev (Bronze),
  newbie@demo.dev (fresh account). Every password is demo1234.
  Not there? Run ./run.sh --seed. The seed prints the full table of accounts.

  On your phone, same wifi: http://$(ipconfig getifaddr en0 2>/dev/null || echo "<your-ip>"):$PORT

  Ctrl+C to stop.

EOF

wait
