#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CATALOG_URL:-http://localhost:8002}/admin/failmode" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"mode":"off","note":"scenario-2 reset"}'
echo
echo "scenario 2 reset"
