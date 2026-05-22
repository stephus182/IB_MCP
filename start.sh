#!/bin/bash
# IBKR Research Dashboard — full stack launcher.
# Usage: ibkr_mcp  (from any directory)

cd "$(dirname "$0")"

# ── 1. Ensure Docker Desktop is running ───────────────────────────────────────
if ! docker info > /dev/null 2>&1; then
  echo "▶ Docker Desktop not running — starting it..."
  open -a Docker
  echo "  Waiting for Docker to be ready..."
  until docker info > /dev/null 2>&1; do
    printf "."
    sleep 2
  done
  echo ""
  echo "  Docker is ready."
fi

# ── 2. Start containers ───────────────────────────────────────────────────────
echo "▶ Starting Docker containers..."
docker-compose up -d
echo ""

# ── 3. Wait for gateway process to be reachable ───────────────────────────────
echo "▶ Waiting for IBKR gateway..."
for i in $(seq 1 30); do
  STATUS=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost:5055/v1/api/iserver/auth/status 2>/dev/null)
  if [ "$STATUS" != "000" ]; then
    break
  fi
  printf "."
  sleep 2
done
echo ""

# ── 4. Open login page and wait for user ─────────────────────────────────────
echo "▶ Opening IBKR login page in Chrome..."
open -a "Google Chrome" https://localhost:5055
echo ""
echo "  Log in with your IBKR credentials."
echo "  Wait until the page shows your account is connected, then come back here."
echo ""
printf "Press Enter once you are logged in... "
read -r
echo ""

# ── 5. Start Streamlit in background, open dashboard once it's ready ──────────
echo "▶ Starting dashboard..."
pkill -f "streamlit run" 2>/dev/null || true
sleep 1

streamlit run dashboard/app.py --server.headless true &
STREAMLIT_PID=$!

echo "  Waiting for dashboard to be ready..."
for i in $(seq 1 20); do
  if curl -s http://localhost:8501 > /dev/null 2>&1; then
    break
  fi
  printf "."
  sleep 1
done
echo ""

echo "▶ Opening dashboard..."
open -a "Google Chrome" http://localhost:8501
echo ""
echo "  Dashboard is running. Press Ctrl+C to stop."
wait $STREAMLIT_PID
