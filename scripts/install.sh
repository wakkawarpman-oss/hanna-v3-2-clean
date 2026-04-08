#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$HOME/.hanna"
TARGET_BIN="$TARGET_DIR/hanna"
LOCAL_BIN_DIR="$HOME/.local/bin"

mkdir -p "$TARGET_DIR" "$LOCAL_BIN_DIR"

cp "$ROOT_DIR/scripts/hanna.sh" "$TARGET_BIN"
chmod +x "$TARGET_BIN"
ln -sf "$TARGET_BIN" "$LOCAL_BIN_DIR/hanna"

if [[ ":$PATH:" != *":$LOCAL_BIN_DIR:"* ]]; then
  SHELL_RC="$HOME/.zshrc"
  if [[ -n "${BASH_VERSION:-}" ]]; then
    SHELL_RC="$HOME/.bashrc"
  fi

  if [[ -f "$SHELL_RC" ]] && ! grep -q "\.local/bin" "$SHELL_RC"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    echo "[install] Added $LOCAL_BIN_DIR to PATH in $SHELL_RC"
  fi
fi

echo "[install] Hanna quick command installed."
echo "[install] Use: hanna --help"
