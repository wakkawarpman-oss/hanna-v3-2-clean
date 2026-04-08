#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

START_STACK=0
SKIP_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --start)
      START_STACK=1
      ;;
    --skip-install)
      SKIP_INSTALL=1
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: bash scripts/prestart.sh [--start] [--skip-install]"
      exit 1
      ;;
  esac
done

echo "HANNA v3.3.0 PREFLIGHT CHECK"

echo "[1/8] Node version"
NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
if [[ "$NODE_MAJOR" -lt 20 ]]; then
  echo "FAIL: Node >= 20 required"
  exit 1
fi
node -v

echo "[2/8] Free memory"
if command -v free >/dev/null 2>&1; then
  free -h || true
elif [[ "$(uname -s)" == "Darwin" ]]; then
  PAGES_FREE="$(vm_stat | awk '/Pages free/ {gsub("\\.","",$3); print $3}')"
  PAGE_SIZE=4096
  if [[ -n "${PAGES_FREE:-}" ]]; then
    FREE_MB=$((PAGES_FREE * PAGE_SIZE / 1024 / 1024))
    echo "Approx free memory: ${FREE_MB}MB"
  else
    echo "Could not determine free memory from vm_stat"
  fi
else
  echo "Memory check command not available"
fi

echo "[3/8] Environment"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if ! grep -q '^JWT_SECRET=' .env; then
  echo "JWT_SECRET=change-me-$(date +%s)" >> .env
  echo "Added JWT_SECRET to .env"
fi

echo "[4/8] Runtime directories"
mkdir -p test/data/{real,errors,large} logs output debug-dumps

echo "[5/8] Install and dependency checks"
if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  npm ci --omit=dev --no-optional
else
  echo "Skipping npm ci (--skip-install)"
fi
npm dedupe
npm ls lodash xml2js

echo "[6/8] Security and tests"
npm run security
npm run test:core
npm run test:all
npm run tui:check

echo "[7/8] Large file parser smoke"
if [[ ! -f test/data/10mb.txt ]]; then
  npm run gen:test-files
fi
npm run parse:large -- test/data/10mb.txt

echo "[8/8] Port checks"
if lsof -i :3000 >/dev/null 2>&1; then
  echo "WARN: Port 3000 is busy"
else
  echo "OK: Port 3000 is free"
fi

if lsof -i :8080 >/dev/null 2>&1; then
  echo "WARN: Port 8080 is busy"
else
  echo "OK: Port 8080 is free"
fi

echo "ALL CHECKS GREEN"

if [[ "$START_STACK" -eq 1 ]]; then
  echo "Starting ultra-perf stack: tui:ultra + start:prod"
  npm run tui:ultra &
  npm run start:prod
fi
