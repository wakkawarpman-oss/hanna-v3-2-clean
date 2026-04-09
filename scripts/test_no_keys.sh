#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-example.com}"
OUT_ROOT="${HANNA_NO_KEY_OUT:-$ROOT/.cache/no-key-smoke}"
MODULES="${HANNA_NO_KEY_MODULES:-core-local}"

rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"

cd "$ROOT"

env \
  -u HIBP_API_KEY \
  -u SHODAN_API_KEY \
  -u CENSYS_API_ID \
  -u CENSYS_API_SECRET \
  -u SEARCH4FACES_API_KEY \
  -u FIRMS_MAP_KEY \
  -u TELEGRAM_BOT_TOKEN \
  -u GETCONTACT_TOKEN \
  -u GETCONTACT_AES_KEY \
  HANNA_TIMEOUT_SUBFINDER_WORKER=10 \
  HANNA_TIMEOUT_HTTPX_PROBE_WORKER=8 \
  HANNA_TIMEOUT_NAABU_WORKER=10 \
  HANNA_TIMEOUT_NMAP_WORKER=12 \
  ./.venv/bin/python3 src/cli.py aggregate \
    --target "$TARGET" \
    --modules "$MODULES" \
    --export-dir "$OUT_ROOT/artifacts" \
    --metadata-file "$OUT_ROOT/no-key-smoke.metadata.json" \
    --json-summary-only \
    --no-preflight