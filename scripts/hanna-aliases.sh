#!/usr/bin/env bash

HANNA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HANNA_BIN="$HANNA_ROOT/scripts/hanna"

hls() {
  "$HANNA_BIN" ls "$@"
}

hpf() {
  "$HANNA_BIN" pf "$@"
}

hui() {
  "$HANNA_BIN" ui --plain "$@"
}

hagg() {
  "$HANNA_BIN" agg "$@"
}

hch() {
  "$HANNA_BIN" ch "$@"
}

hman() {
  "$HANNA_BIN" man "$@"
}

hfs() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" agg --modules full-spectrum --target "$target" "$@"
}

hchainfs() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" ch --modules full-spectrum --target "$target" "$@"
}

hsum() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" sum --target "$target" --text "$*"
}

echo "HANNA shortcuts loaded from $HANNA_BIN"
echo "Available: hls, hpf, hui, hagg, hch, hman, hfs, hchainfs, hsum"