#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-hanna:prod}"
LOOPS="${2:-20}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

for i in $(seq 1 "$LOOPS"); do
  NAME="kill9-${i}"
  docker run -d --name "$NAME" --restart=always "$IMAGE" npm run tui:ultra >/dev/null
  sleep 0.2
  docker kill "$NAME" --signal=KILL >/dev/null || true
  docker rm -f "$NAME" >/dev/null || true
  echo "cycle $i done"
done
