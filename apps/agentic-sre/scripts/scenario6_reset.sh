#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CHECKOUT_URL:-http://localhost:8003}/admin/db/index" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"action":"create"}'
echo
echo "scenario 6 reset: recreated orders_sku_created_idx"
