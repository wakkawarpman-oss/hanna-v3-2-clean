#!/usr/bin/env bash
set -euo pipefail

if ! id -u hanna >/dev/null 2>&1; then
  useradd --system --home /opt/hanna --shell /usr/sbin/nologin --comment "Hanna Parser" hanna
fi

mkdir -p /opt/hanna/{logs,output,tmp,data}
chown -R hanna:hanna /opt/hanna
chmod 750 /opt/hanna
chmod 700 /opt/hanna/logs /opt/hanna/tmp

if [[ -f /opt/hanna/.env.prod ]]; then
  chmod 600 /opt/hanna/.env.prod
  chown hanna:hanna /opt/hanna/.env.prod
fi

echo "hanna user and directories configured"
