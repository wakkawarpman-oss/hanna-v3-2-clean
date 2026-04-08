#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-hanna-parser}"
ALERT_EMAIL="${ALERT_EMAIL:-admin@company.com}"

if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "Hanna OK"
  exit 0
fi

if command -v mail >/dev/null 2>&1; then
  echo "Hanna DOWN" | mail -s "Hanna Parser CRITICAL" "$ALERT_EMAIL"
fi

echo "Hanna DOWN"
exit 1
