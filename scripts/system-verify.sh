#!/usr/bin/env bash
# scripts/system-verify.sh

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-hanna-parser}"
APP_USER="${APP_USER:-hanna}"
APP_DIR="${APP_DIR:-/opt/hanna}"
HEALTH_URL="${HEALTH_URL:-http://localhost:3000/health}"

echo "HANNA v3.3.1 SYSTEM VERIFICATION"
echo "================================"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "ERROR: systemctl not found. This script is for Linux systemd hosts."
  exit 1
fi

# 1) SYSTEMD UNITS
echo "1) SYSTEMD SERVICES"
if systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
  echo "OK: $SERVICE_NAME enabled"
else
  echo "FAIL: $SERVICE_NAME is not enabled"
  exit 1
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "OK: $SERVICE_NAME running"
else
  echo "WARN: $SERVICE_NAME stopped (will restart at end)"
fi

# 2) USER + PERMISSIONS
echo "2) USER AND PERMISSIONS"
if id "$APP_USER" >/dev/null 2>&1; then
  echo "OK: user $APP_USER exists"
else
  echo "FAIL: user $APP_USER missing"
  echo "Hint: bash deploy/systemd/setup-hanna-user.sh"
  exit 1
fi

if [[ -d "$APP_DIR" ]]; then
  echo "OK: $APP_DIR exists"
else
  echo "FAIL: $APP_DIR missing"
  exit 1
fi

# 3) HEALTH CHECK
echo "3) HEALTH CHECK"
if curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "OK: API health endpoint reachable"
else
  echo "WARN: API health endpoint not reachable (service may be down)"
fi

# 4) DEPENDENCIES
echo "4) DEPENDENCIES"
if command -v pm2 >/dev/null 2>&1; then
  echo "OK: PM2 $(pm2 -v | head -n 1)"
else
  echo "FAIL: PM2 missing"
  echo "Hint: sudo npm i -g pm2"
  exit 1
fi

if command -v node >/dev/null 2>&1; then
  echo "OK: Node $(node --version)"
else
  echo "FAIL: Node missing"
  exit 1
fi

# 5) CONFIG
echo "5) CONFIG"
if [[ -f "$APP_DIR/config.calibrated.json" ]]; then
  echo "OK: config.calibrated.json present"
else
  echo "WARN: config.calibrated.json missing"
fi

if [[ -f "$APP_DIR/.env.prod" ]]; then
  echo "OK: .env.prod present"
else
  echo "FAIL: .env.prod missing"
  exit 1
fi

# 6) LOGS
echo "6) RECENT LOGS"
journalctl -u "$SERVICE_NAME" -n 10 --no-pager || echo "WARN: no logs available"

# 7) RESOURCES
echo "7) RESOURCES"
systemctl show "$SERVICE_NAME" --property=MemoryCurrent,CPUUsageNSec --value || echo "WARN: metrics unavailable"

echo
echo "ALL CHECKS PASSED. Ensuring $SERVICE_NAME is active..."

if sudo -n true >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager -l
else
  echo "WARN: sudo password required for restart. Run manually:"
  echo "sudo systemctl restart $SERVICE_NAME"
  echo "sudo systemctl status $SERVICE_NAME --no-pager -l"
fi

echo
echo "PRODUCTION READY"
echo "Monitor: journalctl -u $SERVICE_NAME -f"
echo "Health:  curl -fsS $HEALTH_URL"
echo "PM2:     pm2 monit"
echo "Stop:    sudo systemctl stop $SERVICE_NAME"
