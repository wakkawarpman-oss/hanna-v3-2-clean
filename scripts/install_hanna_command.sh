#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT/scripts/hanna"
BIN_NAME="${HANNA_INSTALL_NAME:-hanna}"
BIN_DIR="${HANNA_INSTALL_BIN_DIR:-$HOME/.local/bin}"
RC_FILE="${HANNA_INSTALL_RC_FILE:-$HOME/.zshrc}"
NO_RC=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage: ./scripts/install_hanna_command.sh [options]

Install a global 'hanna' command without needing 'source'.

Options:
  --bin-dir PATH   Install symlink into PATH (default: $HOME/.local/bin)
  --rc-file PATH   Shell rc file to update with PATH export (default: $HOME/.zshrc)
  --no-rc          Do not modify shell rc file
  --dry-run        Print planned actions without changing files
  -h, --help       Show this help
EOF
}

log() {
  printf '[install-hanna] %s\n' "$*"
}

append_path_if_missing() {
  local rc_file="$1"
  local bin_dir="$2"
  local path_line="export PATH=\"$bin_dir:\$PATH\""

  mkdir -p "$(dirname "$rc_file")"
  touch "$rc_file"

  if grep -Fqx "$path_line" "$rc_file"; then
    log "PATH entry already present in $rc_file"
    return 0
  fi

  {
    printf '\n# HANNA global command\n'
    printf '%s\n' "$path_line"
  } >> "$rc_file"
  log "Added PATH entry to $rc_file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --rc-file)
      RC_FILE="$2"
      shift 2
      ;;
    --no-rc)
      NO_RC=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -x "$TARGET" ]]; then
  printf 'Expected executable wrapper not found: %s\n' "$TARGET" >&2
  exit 1
fi

DEST="$BIN_DIR/$BIN_NAME"

if [[ "$DRY_RUN" == "1" ]]; then
  log "Would create symlink: $DEST -> $TARGET"
  if [[ "$NO_RC" == "0" ]]; then
    log "Would ensure PATH entry in $RC_FILE"
  fi
  exit 0
fi

mkdir -p "$BIN_DIR"
ln -sfn "$TARGET" "$DEST"
log "Installed symlink: $DEST -> $TARGET"

if [[ "$NO_RC" == "0" ]]; then
  append_path_if_missing "$RC_FILE" "$BIN_DIR"
fi

if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
  log "Command is available now: $BIN_NAME"
else
  log "Open a new shell or run: export PATH=\"$BIN_DIR:\$PATH\""
fi

log "Try: $BIN_NAME --help"