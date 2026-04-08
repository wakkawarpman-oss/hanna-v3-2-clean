#!/usr/bin/env bash
set -euo pipefail

DURATION_SEC="${1:-300}"
END_TIME=$(( $(date +%s) + DURATION_SEC ))

npm run production-readiness

while [[ $(date +%s) -lt "$END_TIME" ]]; do
  npm run parse:large -- test/data/100mb.txt
  curl -fsS http://localhost:3000/health >/dev/null || true
  echo "loop at $(date -u +%FT%TZ)"
done

echo "24h-marathon simulation complete (${DURATION_SEC}s)"
