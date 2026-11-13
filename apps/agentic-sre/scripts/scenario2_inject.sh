#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CATALOG_URL:-http://localhost:8002}/admin/failmode" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"mode":"leak","note":"scenario-2 memory leak"}'
echo
echo "scenario 2 injected: catalog leak gauge will climb as traffic arrives"
