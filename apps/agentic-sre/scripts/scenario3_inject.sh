#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CHECKOUT_URL:-http://localhost:8003}/admin/failmode" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"mode":"latency","note":"scenario-3 orders-db latency"}'
echo
echo "scenario 3 injected: checkout runs a heavy Postgres scan"
