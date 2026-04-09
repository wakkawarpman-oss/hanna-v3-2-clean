#!/usr/bin/env bash
# scripts/hanna-dashboard.sh — tmux reference OSINT dashboard
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

# ┌─[STATUS BAR]─────────────────────────────────────────────────────────┐ pane 0
# ├───────────────┬───────────────────────────────────┬─────────────────┤
# │ METRICS TREE  │ GRAPH (largest)                   │ CONTROLS        │ pane 1/3/4
# ├───────────────┴───────────────────────────────────┴─────────────────┤
# │ LIVE LOGS                                                          │ pane 2
# └─────────────────────────────────────────────────────────────────────┘

tmux new-session -d -s "$SESS" -c "$HANNA_ROOT" -n MAIN

# pane 0 — top status bar
tmux send-keys -t "$SESS":MAIN.0 "npm run topbar" Enter

# pane 1 — work area under top bar
tmux split-window -v -t "$SESS":MAIN.0 -c "$HANNA_ROOT" -p 88

# pane 2 — logs at the bottom of work area
tmux split-window -v -t "$SESS":MAIN.1 -c "$HANNA_ROOT" -p 24

# pane 3 — graph area to the right of metrics tree
tmux split-window -h -t "$SESS":MAIN.1 -c "$HANNA_ROOT" -p 72

# pane 4 — controls to the right of graph
tmux split-window -h -t "$SESS":MAIN.3 -c "$HANNA_ROOT" -p 24

tmux send-keys -t "$SESS":MAIN.1 "bash -lc 'while true; do clear; npm run tui:tree --silent 2>&1; sleep 3; done'" Enter
tmux send-keys -t "$SESS":MAIN.3 "bash -lc 'while true; do clear; npm run tui:graph --silent 2>&1; sleep 1; done'" Enter
tmux send-keys -t "$SESS":MAIN.4 "bash -lc 'while true; do clear; npm run tui:controls --silent 2>&1; sleep 4; done'" Enter
tmux send-keys -t "$SESS":MAIN.2 "npm run logs:live 2>/dev/null || echo 'No logs yet — start server first'" Enter

# reference proportions: top ≈ 12%, metrics ≈ 20%, graph ≈ 55%, controls ≈ 13%, logs ≈ 20%
tmux resize-pane -t "$SESS":MAIN.0 -y 3
tmux resize-pane -t "$SESS":MAIN.4 -x 26
tmux resize-pane -t "$SESS":MAIN.1 -x 32

# focus the graph pane
tmux select-pane -t "$SESS":MAIN.3

echo "Dashboard ready — attaching…"
exec tmux attach -t "$SESS"
