#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "FAILFAST LOGIC CHECKS"

# 1) Prevent ad-hoc console logging in runtime paths (allow startup banner logs)
if rg -n "console\.log" app.js app-opt.js routes plugins components --glob '!**/*.spec.js' | rg -v "listening on port"; then
  echo "console.log found in runtime code"
  exit 1
fi

# 2) All tests must pass
npm test

# 3) Block TODO markers in core runtime paths
if rg -n "TODO" app.js app-opt.js routes plugins components; then
  echo "TODO markers found in runtime code"
  exit 1
fi

# 4) Calibration gate
node -e "const { Calibration } = require('./components/calibration'); if (!Calibration.validate().allGreen) process.exit(1);"

echo "FAILFAST PASSED"
