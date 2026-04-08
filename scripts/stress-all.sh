#!/usr/bin/env bash
set -euo pipefail

# Quick suite for ~5 minutes; long-run scenarios are opt-in.
npm run stress:api
npm run stress:files
npm run stress:cache
npm run stress:workers

if [[ "${STRESS_TUI:-0}" == "1" ]]; then
  npm run stress:tui
fi

if [[ "${STRESS_LONG:-0}" == "1" ]]; then
  npm run stress:24h
fi

echo "stress:all complete"
