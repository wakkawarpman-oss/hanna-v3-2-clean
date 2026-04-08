#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running production-readiness checks"

npm run security
npm run test:core
npm run test:all
npm run tui:check
npm run test:parser-errors

if [[ ! -f test/data/10mb.txt ]]; then
	npm run gen:test-files
fi

npm run parse:large -- test/data/10mb.txt

echo "Production-readiness checks passed"
