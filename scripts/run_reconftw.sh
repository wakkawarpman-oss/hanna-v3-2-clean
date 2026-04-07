#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECONFTW_ROOT="${RECONFTW_ROOT:-$ROOT_DIR/tools/reconftw}"
RECONFTW_BASH="${RECONFTW_BASH:-/opt/homebrew/bin/bash}"
RECONFTW_CONFIG="${RECONFTW_CONFIG:-$ROOT_DIR/scripts/reconftw-hanna-macos.cfg}"
RECONFTW_OUTPUT_ROOT="${RECONFTW_OUTPUT_ROOT:-}"
RECONFTW_RATE="${RECONFTW_RATE:-80}"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 <domain-or-url> [extra reconFTW args...]"
  exit 1
fi
shift || true

if [[ ! -x "$RECONFTW_BASH" ]]; then
  RECONFTW_BASH="$(command -v bash)"
fi

if [[ ! -x "$RECONFTW_ROOT/reconftw.sh" ]]; then
  echo "reconFTW not found at $RECONFTW_ROOT/reconftw.sh"
  exit 1
fi

if [[ ! -f "$RECONFTW_CONFIG" ]]; then
  echo "reconFTW config not found at $RECONFTW_CONFIG"
  exit 1
fi

TARGET="${TARGET#http://}"
TARGET="${TARGET#https://}"
TARGET="${TARGET%%/*}"

mkdir -p "$RECONFTW_ROOT/.tmp"
if [[ -n "$RECONFTW_OUTPUT_ROOT" ]]; then
  mkdir -p "$RECONFTW_OUTPUT_ROOT"
fi

export PATH="/opt/homebrew/bin:/opt/homebrew/opt/coreutils/libexec/gnubin:/opt/homebrew/opt/gnu-sed/libexec/gnubin:/Users/admin/go/bin:$PATH"

cd "$RECONFTW_ROOT"

RECONFTW_ARGS=(
  -d "$TARGET"
  -r
  -f "$RECONFTW_CONFIG"
  -q "$RECONFTW_RATE"
  --no-banner
  --no-parallel
)

if [[ -n "$RECONFTW_OUTPUT_ROOT" ]]; then
  RECONFTW_ARGS+=( -o "$RECONFTW_OUTPUT_ROOT" )
fi

exec "$RECONFTW_BASH" "$RECONFTW_ROOT/reconftw.sh" \
  "${RECONFTW_ARGS[@]}" \
  "$@"