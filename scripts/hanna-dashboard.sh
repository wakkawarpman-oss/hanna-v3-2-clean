#!/usr/bin/env bash
# scripts/hanna-dashboard.sh — tmux 6-panel reference OSINT dashboard
set -euo pipefail

HANNA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESS="hanna-dashboard"

if ! command -v tmux &>/dev/null; then
  echo "tmux is required. Install: brew install tmux (macOS) / apt install tmux (Linux)"
  exit 1
fi

if tmux has-session -t "$SESS" 2>/dev/null; then
  echo "Attaching to existing dashboard…"
  exec tmux attach -t "$SESS"
fi

# ┌─[STATUS BAR]────────────────────────────────┐  pane 0
# ├──────────────────────┬──────────────────────┤
# │  METRICS TREE        │  CONTROLS            │  pane 1 / 2
# ├──────────────────────┴──────────────────────┤
# │  GRAPH (largest — latency / throughput)     │  pane 3
# ├─────────────────────────────────────────────┤
# │  LIVE LOGS                                  │  pane 4
# └─────────────────────────────────────────────┘

tmux new-session -d -s "$SESS" -c "$HANNA_ROOT" -n MAIN

# pane 0 — top status bar (small)
tmux send-keys -t "$SESS":MAIN "npm run topbar" Enter

# pane 1 — metrics tree (left mid)
tmux split-window -v -t "$SESS":MAIN.0 -c "$HANNA_ROOT" -p 85
tmux send-keys -t "$SESS":MAIN.1 "watch -n 5 'npm run tui:tree --silent 2>&1'" Enter

# pane 2 — controls (right mid)
tmux split-window -h -t "$SESS":MAIN.1 -c "$HANNA_ROOT" -p 35
tmux send-keys -t "$SESS":MAIN.2 "npm run tui:controls" Enter

# pane 3 — graph (center, largest)
tmux split-window -v -t "$SESS":MAIN.1 -c "$HANNA_ROOT" -p 60
tmux send-keys -t "$SESS":MAIN.3 "npm run tui:graph" Enter

# pane 4 — live logs (bottom)
tmux split-window -v -t "$SESS":MAIN.3 -c "$HANNA_ROOT" -p 30
tmux send-keys -t "$SESS":MAIN.4 "npm run logs:live 2>/dev/null || echo 'No logs yet — start server first'" Enter

# focus the graph pane
tmux select-pane -t "$SESS":MAIN.3

echo "Dashboard ready — attaching…"
exec tmux attach -t "$SESS"
