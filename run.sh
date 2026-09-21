#!/usr/bin/env bash
# Start GoodDeed Go locally. One server on :8000 serves both the API and the
# frontend -- the same arrangement as the deployed Render service, so local
# and production behave identically.
#
#   ./run.sh           start
#   ./run.sh --seed    wipe and reseed the demo data first (see scripts/seed_demo.py)
#   ./run.sh --https   serve over https with a self-signed certificate
#
# Use --https to test on a phone. Browsers refuse to give a page its location
# unless the origin is secure, and "secure" means https:// or localhost -- the
# http://192.168.x.x address below is neither. Without it, every location
# lookup on the phone fails and the app falls back to an approximate position,
# which is the one bug that looks exactly like the app working.
#
# Ctrl+C stops it.

set -euo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8000}
SEED=0
HTTPS=0
for arg in "$@"; do
  case "$arg" in
    --seed)  SEED=1 ;;
    --https) HTTPS=1 ;;
    *) echo "unknown option: $arg"; echo "usage: ./run.sh [--seed] [--https]"; exit 2 ;;
  esac
done

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")

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

if [ "$SEED" = "1" ]; then
  echo "-> seeding demo data"
  python3 scripts/seed_demo.py
fi

SSL_ARGS=()
SCHEME="http"
if [ "$HTTPS" = "1" ]; then
  CERT_DIR=".devcert"
  mkdir -p "$CERT_DIR"
  # Regenerated when the LAN IP changes, since the address is baked into the
  # certificate's SAN and a mismatched one is refused outright rather than
  # merely warned about.
  if [ ! -f "$CERT_DIR/cert.pem" ] || [ "$(cat "$CERT_DIR/.host" 2>/dev/null || true)" != "$LAN_IP" ]; then
    echo "-> generating a self-signed certificate for ${LAN_IP:-localhost}"
    SAN="DNS:localhost,IP:127.0.0.1"
    [ -n "$LAN_IP" ] && SAN="$SAN,IP:$LAN_IP"
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
      -subj "/CN=${LAN_IP:-localhost}" -addext "subjectAltName=$SAN" 2>/dev/null
    echo "$LAN_IP" > "$CERT_DIR/.host"
  fi
  SSL_ARGS=(--ssl-keyfile "$CERT_DIR/key.pem" --ssl-certfile "$CERT_DIR/cert.pem")
  SCHEME="https"
fi

echo "-> starting on :$PORT over $SCHEME"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --reload "${SSL_ARGS[@]}" &
SERVER_PID=$!
trap 'echo; echo "-> stopping"; kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 40); do
  curl -fsSk "$SCHEME://localhost:$PORT/health" >/dev/null 2>&1 && break
  sleep 0.5
done

cat <<EOF

  GoodDeed Go is running
  ----------------------
  App        $SCHEME://localhost:$PORT
  API docs   $SCHEME://localhost:$PORT/docs

  Demo logins: lena@demo.dev (Gold), ana@demo.dev (Silver), sam@demo.dev (Bronze),
  newbie@demo.dev (fresh account). Every password is demo1234.
  Not there? Run ./run.sh --seed. The seed prints the full table of accounts.

  On your phone, same wifi: $SCHEME://${LAN_IP:-<your-ip>}:$PORT
EOF

if [ "$HTTPS" = "1" ]; then
  cat <<'EOF'
  The certificate is self-signed, so the phone will warn once. Tap through it
  ("Advanced" -> "Proceed"). After that the origin counts as secure and the
  browser will offer the location prompt.
EOF
else
  cat <<'EOF'
  Note: on that http:// address the browser will NOT give the page your
  location -- it only does that on https:// or localhost. The app will say it
  is working from an approximate position. Restart with ./run.sh --https to
  test anything location-dependent on a phone.
EOF
fi

echo
echo "  Ctrl+C to stop."
echo

wait
