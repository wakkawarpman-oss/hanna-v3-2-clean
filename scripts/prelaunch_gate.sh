#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="$ROOT/.venv/bin/python3"

if [[ ! -x "$PY_BIN" ]]; then
  PY_BIN="$(command -v python3)"
fi

exec env PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PY_BIN" "$ROOT/scripts/prelaunch_gate.py" "$@"