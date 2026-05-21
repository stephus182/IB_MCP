#!/bin/sh
# Health check: just verify the gateway Java process is accepting connections.
# Authentication state is NOT checked here — that requires browser login.
# Using /tickle (POST) which returns 200 as soon as the JVM is up.

URL="https://localhost:${GATEWAY_PORT}/v1/api/tickle"

STATUS=$(curl -sk -o /dev/null -w "%{http_code}" -X POST -H "Content-Length: 0" "$URL" 2>/dev/null)

if echo "$STATUS" | grep -qE "^[2-5]"; then
    echo "Gateway up (HTTP $STATUS)"
    exit 0
else
    echo "Gateway not yet ready (HTTP $STATUS)"
    exit 1
fi
