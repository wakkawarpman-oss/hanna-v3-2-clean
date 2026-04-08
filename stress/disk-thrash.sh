#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-test/data/stress-1gb.bin}"
SIZE_MB="${2:-1024}"

mkdir -p "$(dirname "$TARGET")"

echo "Generating ${SIZE_MB}MB file: $TARGET"
if command -v dd >/dev/null 2>&1; then
  dd if=/dev/zero of="$TARGET" bs=1M count="$SIZE_MB"
else
  python3 - <<'PY'
from pathlib import Path
import os
p = Path('"$TARGET"')
p.parent.mkdir(parents=True, exist_ok=True)
size = int('"$SIZE_MB"') * 1024 * 1024
with p.open('wb') as f:
    f.write(b'\x00' * size)
PY
fi

npm run parse:large -- "$TARGET"
