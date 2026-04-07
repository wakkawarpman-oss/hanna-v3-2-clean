#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGETS_FILE="${1:-$ROOT/examples/targets.txt}"
OUTPUT_HTML="${2:-$ROOT/runs/exports/html/dossiers/batch_fast.html}"

mkdir -p "$(dirname "$OUTPUT_HTML")"

python "$ROOT/src/run_discovery.py" \
  --targets-file "$TARGETS_FILE" \
  --mode fast-lane \
  --verify \
  --output "$OUTPUT_HTML"

echo "Batch run completed: $OUTPUT_HTML"
