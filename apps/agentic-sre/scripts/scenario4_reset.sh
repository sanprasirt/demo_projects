#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CHECKOUT_URL:-http://localhost:8003}/admin/db/lock" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"action":"release"}'
echo
echo "scenario 4 reset"
