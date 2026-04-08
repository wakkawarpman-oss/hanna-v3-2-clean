#!/usr/bin/env bash

HANNA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HANNA_BIN="$HANNA_ROOT/scripts/hanna"

hls() {
  "$HANNA_BIN" ls "$@"
}

hpf() {
  "$HANNA_BIN" pf "$@"
}

hui() {
  "$HANNA_BIN" ui --plain "$@"
}

hagg() {
  "$HANNA_BIN" agg "$@"
}

hch() {
  "$HANNA_BIN" ch "$@"
}

hman() {
  "$HANNA_BIN" man "$@"
}

hfs() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" agg --modules full-spectrum --target "$target" "$@"
}

hchainfs() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" ch --modules full-spectrum --target "$target" "$@"
}

hsum() {
  local target="${1:-}"
  shift || true
  "$HANNA_BIN" sum --target "$target" --text "$*"
}

hreset() {
  "$HANNA_BIN" reset --confirm --json-only "$@"
}

hstart() {
  npm start --prefix "$HANNA_ROOT" "$@"
}

hstop() {
  if command -v pm2 &>/dev/null; then
    pm2 stop hanna 2>/dev/null || true
  fi
  if command -v systemctl &>/dev/null; then
    sudo systemctl stop hanna-parser 2>/dev/null || true
  fi
  echo "HANNA stopped"
}

hhealth() {
  curl -fsS "${HEALTH_URL:-http://localhost:3000/health}" | python3 -m json.tool 2>/dev/null || curl -fsS "${HEALTH_URL:-http://localhost:3000/health}"
}

hlogs() {
  local log_dir="${HANNA_RUNS_ROOT:-$HANNA_ROOT/runs}/logs"
  if [[ -d "$log_dir" ]]; then
    tail -f "$log_dir"/*.log 2>/dev/null || echo "No log files in $log_dir"
  else
    echo "Log directory $log_dir does not exist"
  fi
}

hanna() {
  cd "$HANNA_ROOT" && npm run system-verify
}

# --- tmux dashboard ---

hdash() {
  bash "$HANNA_ROOT/scripts/hanna-dashboard.sh"
}

hlayout1() { tmux select-layout tiled; }
hlayout2() { tmux select-layout even-horizontal; }
hlayout3() { tmux select-layout main-vertical; }

hlayout-ref() {
  # Reference layout: topbar 10% → tree+controls 20% → graph 50% → logs 20%
  tmux select-pane -t 0
  tmux resize-pane -y 3
  tmux select-pane -t 3
  tmux resize-pane -y 50%
  tmux select-pane -t 4
  tmux resize-pane -y 20%
}

hfocus-top()      { tmux select-pane -t 0; }
hfocus-metrics()  { tmux select-pane -t 1; }
hfocus-controls() { tmux select-pane -t 2; }
hfocus-graph()    { tmux select-pane -t 3; }
hfocus-logs()     { tmux select-pane -t 4; }

htop() { tmux switch-client -t hanna-dashboard 2>/dev/null || hdash; }
hkill() { tmux kill-session -t hanna-dashboard 2>/dev/null && echo "Dashboard killed" || echo "No dashboard session"; }

echo "HANNA shortcuts loaded from $HANNA_BIN"
echo "Available: hls, hpf, hui, hagg, hch, hman, hfs, hchainfs, hsum, hreset, hstart, hstop, hhealth, hlogs, hanna"
echo "Dashboard: hdash, htop, hkill, hlayout1/2/3, hlayout-ref, hfocus-{top,metrics,controls,graph,logs}"