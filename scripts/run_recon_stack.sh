#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
TARGET=""
PERSON_TARGET="${HANNA_PERSON_TARGET:-}"
PERSON_PHONES="${HANNA_PERSON_PHONES:-}"
PERSON_USERNAMES="${HANNA_PERSON_USERNAMES:-}"
SPIDERFOOT_HOST="${SPIDERFOOT_HOST:-127.0.0.1}"
SPIDERFOOT_PORT="${SPIDERFOOT_PORT:-5001}"
SPIDERFOOT_IMAGE="${SPIDERFOOT_IMAGE:-local/spiderfoot:latest}"
SPIDERFOOT_CONTAINER="${SPIDERFOOT_CONTAINER:-hanna-spiderfoot}"
SPIDERFOOT_DATA_DIR="${SPIDERFOOT_DATA_DIR:-$ROOT_DIR/.cache/spiderfoot}"
SPIDERFOOT_QUARANTINE_DIR="${SPIDERFOOT_QUARANTINE_DIR:-$ROOT_DIR/.cache/spiderfoot-quarantine}"
SPIDERFOOT_EXPORT_DIR="${SPIDERFOOT_EXPORT_DIR:-$ROOT_DIR/.cache/spiderfoot-exports}"
SPIDERFOOT_USECASE="${SPIDERFOOT_USECASE:-Passive}"
SPIDERFOOT_READY_TIMEOUT="${SPIDERFOOT_READY_TIMEOUT:-30}"
SPIDERFOOT_SCAN_WAIT_SECONDS="${SPIDERFOOT_SCAN_WAIT_SECONDS:-10}"
SPIDERFOOT_POLL_INTERVAL="${SPIDERFOOT_POLL_INTERVAL:-2}"
SKIP_SPIDERFOOT=0
EXTRA_HANNA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --person-target)
      PERSON_TARGET="${2:-}"
      shift 2
      ;;
    --phones)
      PERSON_PHONES="${2:-}"
      shift 2
      ;;
    --usernames)
      PERSON_USERNAMES="${2:-}"
      shift 2
      ;;
    --skip-spiderfoot)
      SKIP_SPIDERFOOT=1
      shift
      ;;
    --)
      shift
      EXTRA_HANNA_ARGS+=("$@")
      break
      ;;
    -*)
      EXTRA_HANNA_ARGS+=("$1")
      shift
      ;;
    *)
      if [[ -z "$TARGET" ]]; then
        TARGET="$1"
      else
        EXTRA_HANNA_ARGS+=("$1")
      fi
      shift
      ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "usage: $0 <domain-or-url> [--person-target <name>] [--phones <csv>] [--usernames <csv>] [--skip-spiderfoot] [-- extra hanna args]"
  exit 1
fi

TARGET_HOST="${TARGET#http://}"
TARGET_HOST="${TARGET_HOST#https://}"
TARGET_HOST="${TARGET_HOST%%/*}"
SPIDERFOOT_BASE_URL="http://${SPIDERFOOT_HOST}:${SPIDERFOOT_PORT}"

spiderfoot_api_healthy() {
  local scanlist

  if ! curl -fsS "$SPIDERFOOT_BASE_URL/ping" >/dev/null 2>&1; then
    return 1
  fi

  scanlist="$(curl -fsS "$SPIDERFOOT_BASE_URL/scanlist" 2>/dev/null || true)"
  python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if isinstance(data, list) else 1)' <<<"$scanlist"
}

reset_spiderfoot_state() {
  local quarantine_path

  if command -v docker >/dev/null 2>&1; then
    docker rm -f "$SPIDERFOOT_CONTAINER" >/dev/null 2>&1 || true
  fi

  if [[ -d "$SPIDERFOOT_DATA_DIR" ]] && [[ -n "$(find "$SPIDERFOOT_DATA_DIR" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    mkdir -p "$SPIDERFOOT_QUARANTINE_DIR"
    quarantine_path="$SPIDERFOOT_QUARANTINE_DIR/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$quarantine_path"
    find "$SPIDERFOOT_DATA_DIR" -mindepth 1 -maxdepth 1 -exec mv {} "$quarantine_path"/ \;
    echo "SpiderFoot state quarantined to $quarantine_path"
  fi

  mkdir -p "$SPIDERFOOT_DATA_DIR"
}

wait_for_spiderfoot() {
  local elapsed=0

  while (( elapsed < SPIDERFOOT_READY_TIMEOUT )); do
    if spiderfoot_api_healthy; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  return 1
}

ensure_spiderfoot_service() {
  if spiderfoot_api_healthy; then
    echo "SpiderFoot already reachable at $SPIDERFOOT_BASE_URL"
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "SpiderFoot Docker runtime not found; skipping"
    return 1
  fi

  mkdir -p "$SPIDERFOOT_DATA_DIR"

  reset_spiderfoot_state

  docker run -d \
    -p "$SPIDERFOOT_HOST:$SPIDERFOOT_PORT:5001" \
    --name "$SPIDERFOOT_CONTAINER" \
    -v "$SPIDERFOOT_DATA_DIR:/var/lib/spiderfoot" \
    "$SPIDERFOOT_IMAGE" >/dev/null

  if wait_for_spiderfoot; then
    echo "SpiderFoot ready at $SPIDERFOOT_BASE_URL"
    return 0
  fi

  echo "SpiderFoot start attempted, but service is not ready yet"
  return 1
}

export_spiderfoot_scan() {
  local scan_id="$1"
  local export_root="$SPIDERFOOT_EXPORT_DIR/$TARGET_HOST"
  local export_file="$export_root/${scan_id}.json"
  local status_file="$export_root/${scan_id}.status.json"
  local list_file="$export_root/${scan_id}.scanlist.json"
  local log_file="$export_root/${scan_id}.scanlog.json"
  local status_payload=""
  local list_payload=""
  local log_payload=""

  mkdir -p "$export_root"

  if curl -fsS "$SPIDERFOOT_BASE_URL/scanexportjsonmulti?ids=$scan_id" >"$export_file" 2>/dev/null; then
    echo "SpiderFoot export saved: $export_file"
  else
    rm -f "$export_file"
    echo "SpiderFoot export unavailable for $scan_id"
  fi

  status_payload="$(curl -fsS "$SPIDERFOOT_BASE_URL/scanstatus?id=$scan_id" 2>/dev/null || true)"
  if [[ -n "$status_payload" ]]; then
    printf '%s\n' "$status_payload" >"$status_file"
    echo "SpiderFoot status saved: $status_file"
  fi

  list_payload="$(curl -fsS "$SPIDERFOOT_BASE_URL/scanlist" 2>/dev/null || true)"
  if [[ -n "$list_payload" ]]; then
    printf '%s\n' "$list_payload" >"$list_file"
  fi

  log_payload="$(curl -fsS "$SPIDERFOOT_BASE_URL/scanlog?id=$scan_id&limit=50" 2>/dev/null || true)"
  if [[ -n "$log_payload" ]]; then
    printf '%s\n' "$log_payload" >"$log_file"
    echo "SpiderFoot log saved: $log_file"
  fi
}

start_spiderfoot_scan() {
  local scan_name raw_response http_code scan_response scan_id list_json status elapsed attempt

  scan_name="HANNA-${TARGET_HOST//[^A-Za-z0-9_.-]/-}-$(date +%Y%m%d-%H%M%S)"
  for attempt in 1 2; do
    raw_response="$(curl -sS -G \
      -H 'Accept: application/json' \
      --data-urlencode "scanname=$scan_name" \
      --data-urlencode "scantarget=$TARGET_HOST" \
      --data-urlencode "modulelist=" \
      --data-urlencode "typelist=" \
      --data-urlencode "usecase=$SPIDERFOOT_USECASE" \
      -w '\n%{http_code}' \
      "$SPIDERFOOT_BASE_URL/startscan" || true)"
    http_code="${raw_response##*$'\n'}"
    scan_response="${raw_response%$'\n'*}"

    if [[ "$http_code" == "200" ]]; then
      break
    fi

    echo "SpiderFoot startscan HTTP $http_code; restarting service"
    reset_spiderfoot_state
    ensure_spiderfoot_service || true
  done

  if [[ "$http_code" != "200" ]]; then
    echo "SpiderFoot scan start failed: $scan_response"
    return 1
  fi

  scan_id="$(printf '%s' "$scan_response" | python3 -c 'import json, sys; data = json.load(sys.stdin); print(data[1] if isinstance(data, list) and len(data) > 1 and data[0] == "SUCCESS" else "")')"

  if [[ -z "$scan_id" ]]; then
    echo "SpiderFoot scan start returned: $scan_response"
    return 1
  fi

  echo "SpiderFoot scan started: $scan_id ($scan_name, usecase=$SPIDERFOOT_USECASE)"

  if (( SPIDERFOOT_SCAN_WAIT_SECONDS <= 0 )); then
    return 0
  fi

  elapsed=0
  while (( elapsed < SPIDERFOOT_SCAN_WAIT_SECONDS )); do
    sleep "$SPIDERFOOT_POLL_INTERVAL"
    elapsed=$((elapsed + SPIDERFOOT_POLL_INTERVAL))
    list_json="$(curl -fsS "$SPIDERFOOT_BASE_URL/scanlist" 2>/dev/null || true)"
    status="$(SCAN_ID="$scan_id" python3 -c 'import json, os, sys
scan_id = os.environ["SCAN_ID"]
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
for row in data:
    if isinstance(row, list) and row and row[0] == scan_id:
        print(row[6] if len(row) > 6 else "")
        break
else:
    print("")' <<<"$list_json")"

    if [[ -n "$status" ]]; then
      echo "SpiderFoot status: $status"
    fi

    case "$status" in
      FINISHED|ERROR|ABORTED)
        break
        ;;
    esac
  done

  export_spiderfoot_scan "$scan_id"

  return 0
}

echo "[1/4] reconFTW macOS profile"
"$ROOT_DIR/scripts/run_reconftw.sh" "$TARGET_HOST"

if [[ "$SKIP_SPIDERFOOT" -eq 0 ]]; then
  echo "[2/4] SpiderFoot API automation"
  if ensure_spiderfoot_service; then
    start_spiderfoot_scan || true
  fi
else
  echo "[2/4] SpiderFoot skipped by flag"
fi

if command -v nuclei >/dev/null 2>&1; then
  echo "[3/4] Standalone nuclei quick pass"
  nuclei -u "$TARGET" -severity high,critical -rate-limit 50 -silent || true
else
  echo "[3/4] nuclei not found in PATH; skipping standalone pass"
fi

if [[ -n "$PERSON_TARGET" ]]; then
  echo "[4/4] HANNA person-deep preset"
  python3 "$SRC_DIR/cli.py" aggregate \
    --target "$PERSON_TARGET" \
    --modules person-deep \
    --phones "$PERSON_PHONES" \
    --usernames "$PERSON_USERNAMES" \
    "${EXTRA_HANNA_ARGS[@]}"
else
  echo "[4/4] No person target provided; skipping person OSINT"
fi