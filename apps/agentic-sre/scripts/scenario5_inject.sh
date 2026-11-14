#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CHECKOUT_URL:-http://localhost:8003}/admin/db/connections" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"action":"hold"}'
echo
echo "scenario 5 injected: sre-hold sessions saturate max_connections"
