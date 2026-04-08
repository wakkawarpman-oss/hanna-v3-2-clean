#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python3" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python3" -m pip install -r "$ROOT/requirements.txt"

if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

chmod +x "$ROOT/scripts/hanna" "$ROOT/scripts/hanna-aliases.sh" "$ROOT/scripts/setup_hanna.sh"

echo "HANNA local environment is ready in: $ROOT"
echo "Virtualenv: $VENV_DIR"
echo "Next commands:"
echo "  source $VENV_DIR/bin/activate"
echo "  ./scripts/hanna pf"
echo "  source scripts/hanna-aliases.sh"

"$ROOT/scripts/hanna" pf || true