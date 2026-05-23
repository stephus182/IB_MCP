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
  if echo "$STATUS" | grep -qE '^[2-5]'; then
    break
  fi
  printf "."
  sleep 2
done
echo ""

# ── 4. Open login page and wait for authenticated session ────────────────────
echo "▶ Opening IBKR login page in Chrome..."
open -a "Google Chrome" https://localhost:5055
echo ""
echo "  Complete the full login in Chrome:"
echo "    1. Enter your IBKR username and password"
echo "    2. Complete 2FA when prompted (challenge code → IBKR Mobile → response code)"
echo "    3. Wait for the browser to show: 'Client login succeeds'"
echo ""

# Flush any buffered stdin so a stray Enter doesn't skip the prompt
read -r -t 0.1 _discard 2>/dev/null || true

printf "Press Enter here once Chrome shows 'Client login succeeds'... "
read -r
echo ""

# Verify the gateway is actually authenticated before proceeding
echo "▶ Verifying IBKR session..."
AUTHED=0
for i in $(seq 1 15); do
  RESULT=$(.venv/bin/python3 -c "
import sys; sys.path.insert(0,'dashboard')
from tools import ibkr_client
print('ok' if ibkr_client.ping() else 'fail')
" 2>/dev/null)
  if [ "$RESULT" = "ok" ]; then
    AUTHED=1
    break
  fi
  printf "."
  sleep 2
done
echo ""

if [ "$AUTHED" = "0" ]; then
  echo "  ✕ Gateway not authenticated — session was not established."
  echo "    Go back to Chrome, reload https://localhost:5055, log in again,"
  echo "    and wait for 'Client login succeeds' before pressing Enter."
  echo ""
  printf "Press Enter to try verification again... "
  read -r -t 0.1 _discard 2>/dev/null || true
  read -r
  echo ""
  RESULT=$(.venv/bin/python3 -c "
import sys; sys.path.insert(0,'dashboard')
from tools import ibkr_client
print('ok' if ibkr_client.ping() else 'fail')
" 2>/dev/null)
  if [ "$RESULT" != "ok" ]; then
    echo "  ✕ Still not authenticated. Starting dashboard anyway — use the ↺ Retry IBKR button once logged in."
    echo ""
  fi
fi

[ "$AUTHED" = "1" ] && echo "  ✔ IBKR session active."
echo ""

# ── 5. Start Streamlit as a detached daemon ───────────────────────────────────
echo "▶ Starting dashboard..."
pkill -f "streamlit run" 2>/dev/null || true
sleep 1

REPO_DIR="$(pwd)"
nohup .venv/bin/streamlit run dashboard/app.py --server.headless true \
  > "$REPO_DIR/.streamlit.log" 2>&1 &
echo $! > "$REPO_DIR/.streamlit.pid"

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
echo "  Dashboard is running in the background."
echo "  Run 'ibkr_stop' to shut it down."
