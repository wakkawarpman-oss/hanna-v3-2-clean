#!/usr/bin/env bash
set -euo pipefail

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for apocalypse mode"
  exit 1
fi

SESSION="apocalypse"
tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"

tmux new-session -d -s "$SESSION" "npm run stress:api"
tmux split-window -h -t "$SESSION" "npm run stress:files"
tmux split-window -v -t "$SESSION":0.1 "npm run stress:report"

tmux select-layout -t "$SESSION" tiled
tmux attach -t "$SESSION"
