#!/bin/bash
# Start the full IBKR research stack.
# Run from anywhere: ibkr_mcp

set -e
cd "$(dirname "$0")"

echo "▶ Starting Docker containers..."
docker-compose up -d

echo ""
echo "▶ Waiting for gateway to be ready..."
for i in $(seq 1 30); do
  STATUS=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost:5055/v1/api/iserver/auth/status 2>/dev/null)
  if [ "$STATUS" != "000" ]; then
    break
  fi
  printf "."
  sleep 2
done
echo ""

echo "▶ Opening IBKR login page..."
open https://localhost:5055

echo ""
echo "  → Log in with your IBKR credentials in the browser that just opened"
echo ""
echo "Press Enter once you have logged in..."
read -r

echo "▶ Starting dashboard..."
pkill -f "streamlit run" 2>/dev/null || true
sleep 1
open http://localhost:8501
streamlit run dashboard/app.py
