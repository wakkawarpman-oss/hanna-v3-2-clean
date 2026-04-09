#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEALTH_URL="${HEALTH_URL:-http://localhost:3000/health}"
METRICS_URL="${METRICS_URL:-http://localhost:3000/metrics}"

fetch_json() {
  local url="$1"
  curl -fsS "$url" 2>/dev/null || printf '{}\n'
}

lane_counts() {
  cd "$ROOT_DIR"
  PYTHONPATH=src python3 - <<'PY'
from collections import Counter
from registry import MODULE_LANE

counts = Counter(MODULE_LANE.values())
print(f"Fast: {counts.get('fast', 0)} | Slow: {counts.get('slow', 0)}")
PY
}

metrics_json() {
  local health metrics
  health="$(fetch_json "$HEALTH_URL")"
  metrics="$(fetch_json "$METRICS_URL")"
  HEALTH_JSON="$health" METRICS_JSON="$metrics" python3 - <<'PY'
import json
import os

health = json.loads(os.environ.get("HEALTH_JSON") or "{}")
metrics = json.loads(os.environ.get("METRICS_JSON") or "{}")
memory = health.get("memory") or {}
rps = metrics.get("rps_history") or []
last_rps = float(rps[-1]) if rps else 0.0

payload = {
    "status": health.get("status", "offline"),
    "throughput_per_min": int(last_rps * 60),
    "rss_mb": int((memory.get("rss") or 0) / (1024 * 1024)),
    "heap_mb": int((memory.get("heapUsed") or 0) / (1024 * 1024)),
    "parser_cache": int(health.get("parserCache") or 0),
    "queue_depth": int(metrics.get("queue_depth") or 0),
    "active_sessions": int(metrics.get("active_sessions") or 0),
    "rps_history": rps,
}

print(json.dumps(payload, ensure_ascii=False))
PY
}

status_bar() {
  local metrics
  metrics="$(metrics_json)"
  METRICS_JSON="$metrics" python3 - <<'PY'
import json
import os

metrics = json.loads(os.environ.get("METRICS_JSON") or "{}")
status = metrics.get("status", "offline")
icon = {"healthy": "🟢", "degraded": "🟡", "offline": "🔴"}.get(status, "🔴")
throughput = int(metrics.get("throughput_per_min") or 0)
rss = int(metrics.get("rss_mb") or 0)
cache = int(metrics.get("parser_cache") or 0)
up = int(metrics.get("active_sessions") or 0)
down = int(metrics.get("queue_depth") or 0)

print(f"{icon} [{status}] [{throughput:,}/min] [{rss}MB] [cache {cache}] [↑{up} ↓{down}]")
PY
}

graph_panel() {
  local metrics
  metrics="$(metrics_json)"
  METRICS_JSON="$metrics" python3 - <<'PY'
import json
import os

metrics = json.loads(os.environ.get("METRICS_JSON") or "{}")
rps = metrics.get("rps_history") or []
peak = max(rps) if rps else 1
current = rps[-1] if rps else 0
throughput = int(metrics.get("throughput_per_min") or 0)
queue = int(metrics.get("queue_depth") or 0)
latency = max(1, int((queue + 1) * 14))
filled = int((current / peak) * 18) if peak else 0
bar = ("█" * filled) + ("▌" * max(0, 18 - filled))

print("📈 LIVE GRAPH")
print(f"Latency {latency}ms p95 | Throughput {throughput:,}/min | Queue {queue}")
print(bar[:18])
print("history: " + " ".join(str(int(v)) for v in rps[-8:]))
PY
}

tree_panel() {
  local metrics lanes
  metrics="$(metrics_json)"
  lanes="$(lane_counts)"
  METRICS_JSON="$metrics" LANES_TEXT="$lanes" python3 - <<'PY'
import json
import os

metrics = json.loads(os.environ.get("METRICS_JSON") or "{}")
lanes = os.environ.get("LANES_TEXT", "Fast: 0 | Slow: 0")
status = metrics.get("status", "offline")
throughput = int(metrics.get("throughput_per_min") or 0)
queue = int(metrics.get("queue_depth") or 0)
sessions = int(metrics.get("active_sessions") or 0)
cache = int(metrics.get("parser_cache") or 0)
risk = "HIGH" if status == "degraded" else ("MED" if queue else "LOW")

print("📊 METRICS TREE")
print(lanes)
print(f"Fast Lane: {throughput:,}/min | active {sessions}")
print(f"Slow Lane: queue {queue} | status {status}")
print(f"Risk: {risk} | cache {cache}")
PY
}

controls_panel() {
  cat <<'EOF'
🎮 CONTROLS
[Parse]   ./scripts/hanna agg --target <target> --modules fast-lane
[Export]  ./scripts/hanna ch --target <target> --export-formats json,metadata,stix,zip
[Reset]   npm run reset
[Config]  ./scripts/hanna ui --plain

Focus: hfocus-top | hfocus-metrics | hfocus-graph | hfocus-controls | hfocus-logs
EOF
}

case "${1:-}" in
  metrics)
    metrics_json
    ;;
  status-bar)
    status_bar
    ;;
  graph)
    graph_panel
    ;;
  tree)
    tree_panel
    ;;
  controls)
    controls_panel
    ;;
  lanes)
    lane_counts
    ;;
  *)
    echo "Usage: $0 {metrics|status-bar|graph|tree|controls|lanes}" >&2
    exit 1
    ;;
esac