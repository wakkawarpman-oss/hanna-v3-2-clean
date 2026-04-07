#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_DIR="${1:-$ROOT/examples/sample_drop}"
TARGET="${2:-Example Target}"

python "$ROOT/src/intake_drop_folder.py" \
  --input-dir "$INPUT_DIR" \
  --target "$TARGET" \
  --profile username \
  --mode fast-lane \
  --verify
