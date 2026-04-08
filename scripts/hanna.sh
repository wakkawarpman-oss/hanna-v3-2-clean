#!/usr/bin/env bash
set -euo pipefail

# Hanna OSINT & KESB quick operations wrapper.
# This script is intentionally separate from scripts/hanna (Python CLI wrapper).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="${HOME}/.hanna"
PID_FILE="$STATE_DIR/api.pid"
LOG_FILE="$STATE_DIR/api.log"

mkdir -p "$STATE_DIR"

compose_cmd() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return
  fi
  echo ""
}

api_login_token() {
  curl -s -X POST "http://localhost:3000/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@example.com","password":"admin-secret"}' | jq -r '.accessToken // empty'
}

start_local_api() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[hanna] API already running with PID $(cat "$PID_FILE")"
    return
  fi

  echo "[hanna] Starting local API..."
  (cd "$ROOT_DIR" && JWT_SECRET="${JWT_SECRET:-local-stage2-secret}" node app.js >>"$LOG_FILE" 2>&1 & echo $! >"$PID_FILE")
  sleep 1

  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[hanna] API started (PID $(cat "$PID_FILE"))"
  else
    echo "[hanna] API failed to start. See $LOG_FILE"
    exit 1
  fi
}

stop_local_api() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" || true
    rm -f "$PID_FILE"
    echo "[hanna] API stopped"
  else
    rm -f "$PID_FILE"
    echo "[hanna] API is not running"
  fi
}

cmd_start() {
  local compose
  compose="$(compose_cmd)"

  if [[ -n "$compose" ]] && [[ -f "$ROOT_DIR/docker-compose.tui.yml" ]]; then
    echo "[hanna] Starting via docker compose (api + tui)..."
    (cd "$ROOT_DIR" && $compose -f docker-compose.tui.yml up -d api)
  else
    start_local_api
  fi

  cmd_status
}

cmd_tui() {
  echo "[hanna] Launching TUI..."
  (cd "$ROOT_DIR" && npm run tui)
}

cmd_test() {
  echo "[hanna] Running Node contract tests..."
  (cd "$ROOT_DIR" && npm test)

  echo "[hanna] Running Python regression tests..."
  (cd "$ROOT_DIR" && python3 -m pytest -q tests/*.py)

  echo "[hanna] All tests passed"
}

cmd_contract() {
  echo "[hanna] Running Gate 2 contract checks..."

  local jwt
  jwt="$(api_login_token)"
  if [[ -z "$jwt" ]]; then
    echo "[hanna] Unable to get JWT from /auth/login"
    exit 1
  fi

  local code

  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:3000/adapters/shodan/run)"
  [[ "$code" == "401" ]] || { echo "[hanna] Expected 401 missing auth, got $code"; exit 1; }

  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Authorization: Bearer invalid' http://localhost:3000/adapters/shodan/run)"
  [[ "$code" == "401" ]] || { echo "[hanna] Expected 401 invalid token, got $code"; exit 1; }

  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $jwt" http://localhost:3000/adapters/shodan/run)"
  [[ "$code" == "202" ]] || { echo "[hanna] Expected 202 valid run, got $code"; exit 1; }

  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $jwt" http://localhost:3000/adapters/unknown/run)"
  [[ "$code" == "404" ]] || { echo "[hanna] Expected 404 unknown adapter, got $code"; exit 1; }

  echo "[hanna] Contract check passed (401/401/202/404)"
}

cmd_status() {
  local jwt
  jwt="$(api_login_token)"

  if [[ -z "$jwt" ]]; then
    echo "[hanna] API status: unavailable (login failed)"
    return 1
  fi

  echo "[hanna] API status: reachable"

  echo "[hanna] Metrics:"
  curl -s -H "Authorization: Bearer $jwt" http://localhost:3000/metrics | jq .
}

cmd_logs() {
  local compose
  compose="$(compose_cmd)"

  if [[ -n "$compose" ]] && [[ -f "$ROOT_DIR/docker-compose.tui.yml" ]]; then
    echo "[hanna] docker compose logs (api, last 50 lines)"
    (cd "$ROOT_DIR" && $compose -f docker-compose.tui.yml logs --tail=50 api)
    return
  fi

  if [[ -f "$LOG_FILE" ]]; then
    echo "[hanna] local API logs (last 50 lines)"
    tail -50 "$LOG_FILE"
  else
    echo "[hanna] No log file at $LOG_FILE"
  fi
}

cmd_stop() {
  local compose
  compose="$(compose_cmd)"

  if [[ -n "$compose" ]] && [[ -f "$ROOT_DIR/docker-compose.tui.yml" ]]; then
    (cd "$ROOT_DIR" && $compose -f docker-compose.tui.yml down) || true
  fi

  stop_local_api
}

cmd_init() {
  local target_dir="$STATE_DIR/hanna-v3-2-clean"

  if [[ ! -d "$target_dir/.git" ]]; then
    echo "[hanna] Cloning repository into $target_dir"
    git clone https://github.com/wakkawarpman-oss/hanna-v3-2-clean.git "$target_dir"
  else
    echo "[hanna] Repository already exists, pulling latest changes"
    (cd "$target_dir" && git pull --ff-only)
  fi

  (cd "$target_dir" && npm install)

  cp "$target_dir/scripts/hanna.sh" "$STATE_DIR/hanna"
  chmod +x "$STATE_DIR/hanna"

  mkdir -p "$HOME/.local/bin"
  ln -sf "$STATE_DIR/hanna" "$HOME/.local/bin/hanna"

  echo "[hanna] Installed quick command at $HOME/.local/bin/hanna"
  echo "[hanna] Ensure $HOME/.local/bin is in PATH"
}

usage() {
  cat <<'EOF'
Hanna OSINT & KESB quick commands

Usage:
  hanna start      Start API stack (docker if available, local fallback)
  hanna tui        Launch TUI dashboard
  hanna test       Run Node + Python tests
  hanna contract   Run Gate 2 API contract smoke (401/401/202/404)
  hanna status     Show API/metrics status
  hanna logs       Show recent API logs
  hanna stop       Stop running services
  hanna init       Clone/install under ~/.hanna and create command link
EOF
}

case "${1:-}" in
  start) cmd_start ;;
  tui) cmd_tui ;;
  test) cmd_test ;;
  contract) cmd_contract ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  stop) cmd_stop ;;
  init) cmd_init ;;
  ""|-h|--help|help) usage ;;
  *)
    echo "[hanna] Unknown command: $1"
    usage
    exit 1
    ;;
esac
