#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

sudo cp "$ROOT_DIR/deploy/systemd/hanna-parser.service" /etc/systemd/system/
sudo cp "$ROOT_DIR/deploy/systemd/hanna-healthcheck.service" /etc/systemd/system/

bash "$ROOT_DIR/deploy/systemd/setup-hanna-user.sh"

sudo -u hanna bash -lc '
  cd /opt/hanna
  if [[ ! -d .git ]]; then
    git clone https://github.com/wakkawarpman-oss/hanna-v3-2-clean .
  else
    git pull --ff-only
  fi
  npm ci --omit=dev
  [[ -f .env.prod ]] || cp .env.example .env.prod
'

sudo systemctl daemon-reload
sudo systemctl enable hanna-parser.service
sudo systemctl restart hanna-parser.service

sudo systemctl --no-pager status hanna-parser.service
curl -fsS http://localhost:3000/health
