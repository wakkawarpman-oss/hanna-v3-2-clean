#!/usr/bin/env bash
set -euo pipefail

LIMIT="${1:-25}"

if command -v cpulimit >/dev/null 2>&1; then
  cpulimit -l "$LIMIT" -- npm run tui:ultra
else
  echo "cpulimit not installed. Running tui:ultra without CPU throttle."
  npm run tui:ultra
fi
