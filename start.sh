#!/bin/bash
# Start the full IBKR research stack.
# Run from repo root: ./start.sh

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

echo "▶ Gateway is up. Now log in:"
echo ""
echo "  → Open https://localhost:5055 in your browser"
echo "  → Enter your IBKR credentials and complete 2FA"
echo ""
echo "Press Enter once you have logged in..."
read -r

echo "▶ Starting dashboard..."
pkill -f "streamlit run" 2>/dev/null || true
sleep 1
streamlit run dashboard/app.py
