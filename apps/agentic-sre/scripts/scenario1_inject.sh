#!/bin/sh
set -eu
token="${ADMIN_TOKEN:-demo-admin}"
curl -sf -X POST "${CATALOG_URL:-http://localhost:8002}/admin/failmode" \
  -H "content-type: application/json" \
  -H "x-admin-token: ${token}" \
  -d '{"mode":"error","note":"scenario-1 bad deploy catalog-v1.4.2"}'
echo
curl -sf -X POST "${GITLAB_PUBLIC_URL:-http://localhost:8929}/admin/fire-webhooks" \
  -H "content-type: application/json" \
  -d '{"scenario":"bad-deploy"}'
echo
echo "scenario 1 injected: catalog 5xx, deployment webhook sent"
