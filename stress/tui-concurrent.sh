#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-hanna:prod}"
COUNT="${2:-50}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

for i in $(seq 1 "$COUNT"); do
  docker run -d --name "tui-${i}" --cpus=0.1 "$IMAGE" npm run tui:ultra >/dev/null
  echo "started tui-${i}"
done

docker ps --filter "name=tui-" --format '{{.Names}}'
