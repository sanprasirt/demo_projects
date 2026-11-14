#!/bin/sh
# Run every incident scenario against the mock stack and print a pass/fail table.
# Start the stack first, from this app directory:
#   docker compose --profile mock up --build
# Then:
#   scripts/e2e_all.sh
# Optional arguments select scenarios by number or name: scripts/e2e_all.sh 4 6
set -eu
cd "$(dirname "$0")/.."
exec python3 scripts/e2e_all.py "$@"
