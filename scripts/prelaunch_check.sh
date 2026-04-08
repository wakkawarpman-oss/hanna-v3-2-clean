#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="$ROOT/.venv/bin/python3"
STAMP="$(date +%Y%m%dT%H%M%S)"
OUT_DIR="${HANNA_PRELAUNCH_OUT_DIR:-$ROOT/.cache/prelaunch/$STAMP}"
RUN_LIVE_SMOKE="${HANNA_RUN_LIVE_SMOKE:-0}"
RUN_FULL_REHEARSAL="${HANNA_RUN_FULL_REHEARSAL:-0}"
FULL_REHEARSAL_TARGET="${HANNA_FULL_REHEARSAL_TARGET:-}"
FULL_REHEARSAL_MODULES="${HANNA_FULL_REHEARSAL_MODULES:-full-spectrum}"
FULL_REHEARSAL_REPORT_MODE="${HANNA_FULL_REHEARSAL_REPORT_MODE:-shareable}"

if [[ ! -x "$PY_BIN" ]]; then
  PY_BIN="$(command -v python3)"
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

FAILURES=0
STATUS_FILE="$OUT_DIR/status.txt"

slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//'
}

log() {
  printf '[prelaunch] %s\n' "$*" >&2
}

run_step() {
  local name="$1"
  shift
  local slug
  local started_at
  local finished_at
  local rc=0

  slug="$(slugify "$name")"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "$name"

  if "$@"; then
    printf 'PASS %s\n' "$name" >> "$STATUS_FILE"
    rc=0
  else
    rc=$?
    printf 'FAIL %s (exit=%s)\n' "$name" "$rc" >> "$STATUS_FILE"
    FAILURES=$((FAILURES + 1))
  fi

  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$OUT_DIR/$slug.step.json" <<EOF
{"name":$(printf '%s' "$name" | "$PY_BIN" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),"slug":$(printf '%s' "$slug" | "$PY_BIN" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),"status":"$( [[ "$rc" -eq 0 ]] && printf 'pass' || printf 'fail' )","exit_code":$rc,"started_at":"$started_at","finished_at":"$finished_at"}
EOF

  return 0
}

generate_final_summary() {
  env \
    PRELAUNCH_OUT_DIR="$OUT_DIR" \
    PRELAUNCH_RUN_LIVE_SMOKE="$RUN_LIVE_SMOKE" \
    PRELAUNCH_RUN_FULL_REHEARSAL="$RUN_FULL_REHEARSAL" \
    PRELAUNCH_FULL_REHEARSAL_TARGET="$FULL_REHEARSAL_TARGET" \
    PRELAUNCH_FULL_REHEARSAL_MODULES="$FULL_REHEARSAL_MODULES" \
    "$PY_BIN" - <<'PY'
import json
import os
import re
from pathlib import Path

out_dir = Path(os.environ["PRELAUNCH_OUT_DIR"])
run_live_smoke = os.environ.get("PRELAUNCH_RUN_LIVE_SMOKE") == "1"
run_full_rehearsal = os.environ.get("PRELAUNCH_RUN_FULL_REHEARSAL") == "1"
full_rehearsal_target = os.environ.get("PRELAUNCH_FULL_REHEARSAL_TARGET") or None
full_rehearsal_modules = os.environ.get("PRELAUNCH_FULL_REHEARSAL_MODULES") or None
step_paths = sorted(out_dir.glob("*.step.json"))

stages = [json.loads(path.read_text(encoding="utf-8")) for path in step_paths]
status_map = {stage["slug"]: stage for stage in stages}

def load_json(path_name):
    path = out_dir / path_name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

def count_nonempty_err_files():
    count = 0
    files = []
    for path in sorted(out_dir.glob("*.err")):
        text = path.read_text(encoding="utf-8", errors="replace")
        meaningful_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.startswith("[prelaunch]")
        ]
        if meaningful_lines:
            count += 1
            files.append(path.name)
    return count, files

def parse_pytest_summary(path_name):
    path = out_dir / path_name
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"=+\s+(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) skipped)?\s+in\s+([0-9.]+)s\s+=+", text)
    if not match:
        return None
    return {
        "passed": int(match.group(1)),
        "failed": int(match.group(2) or 0),
        "skipped": int(match.group(3) or 0),
        "duration_seconds": float(match.group(4)),
    }

preflight = load_json("preflight.json")
smart_summary = load_json("smart-summary.json")
live_smoke = load_json("live-smoke.json")
rehearsal_verification = load_json("full-rehearsal.verification.json")
pytest_summary = parse_pytest_summary("pytest.txt")
nonempty_err_count, nonempty_err_files = count_nonempty_err_files()

final_summary = {
    "schema_version": 1,
    "bundle_root": str(out_dir),
    "generated_from": "scripts/prelaunch_check.sh",
    "overall_status": "pass" if all(stage.get("status") == "pass" for stage in stages) else "fail",
    "failure_count": sum(1 for stage in stages if stage.get("status") != "pass"),
    "stage_count": len(stages),
    "nonempty_error_files": {
        "count": nonempty_err_count,
        "files": nonempty_err_files,
    },
    "stages": stages,
    "checks": {
        "preflight": {
            "status": status_map.get("canonical-preflight-json", {}).get("status", "unknown"),
            "summary": preflight.get("summary") if isinstance(preflight, dict) else None,
            "modules": preflight.get("modules") if isinstance(preflight, dict) else None,
            "path": "preflight.json",
        },
        "smart_summary": {
            "status": status_map.get("summary-schema-smoke", {}).get("status", "unknown"),
            "path": "smart-summary.json",
            "risk_flag_codes": [flag.get("code") for flag in smart_summary.get("risk_flags", [])] if isinstance(smart_summary, dict) else [],
            "observable_counts": {
                key: len(value)
                for key, value in (smart_summary.get("observables", {}) if isinstance(smart_summary, dict) else {}).items()
                if isinstance(value, list)
            },
        },
        "focused_regression": {
            "status": status_map.get("focused-regression-pack", {}).get("status", "unknown"),
            "path": "pytest.txt",
            "summary": pytest_summary,
        },
        "live_smoke": {
            "enabled": run_live_smoke,
            "status": status_map.get("optional-no-credential-chain-smoke", {}).get("status", "not-run") if run_live_smoke else "not-run",
            "path": "live-smoke.json" if run_live_smoke else None,
            "runtime_summary": live_smoke,
        },
        "full_rollout_rehearsal": {
            "enabled": run_full_rehearsal,
            "status": status_map.get("optional-full-rollout-rehearsal", {}).get("status", "not-run") if run_full_rehearsal else "not-run",
            "artifact_verification_status": status_map.get("optional-rehearsal-artifact-verification", {}).get("status", "not-run") if run_full_rehearsal else "not-run",
            "target": full_rehearsal_target if run_full_rehearsal else None,
            "modules": full_rehearsal_modules if run_full_rehearsal else None,
            "runtime_path": "full-rehearsal.runtime.json" if run_full_rehearsal else None,
            "verification_path": "full-rehearsal.verification.json" if run_full_rehearsal else None,
            "verification": rehearsal_verification,
        },
    },
}

(out_dir / "final-summary.json").write_text(json.dumps(final_summary, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

cd "$ROOT"

log "Output directory: $OUT_DIR"
printf 'root=%s\npython=%s\nout_dir=%s\n' "$ROOT" "$PY_BIN" "$OUT_DIR" > "$OUT_DIR/context.txt"

run_step "Legacy wrapper inventory" \
  "$PY_BIN" "$ROOT/run_discovery.py" --list-modules \
  > "$OUT_DIR/run_discovery.list.txt" 2> "$OUT_DIR/run_discovery.list.err"

run_step "Root UI wrapper help" \
  "$PY_BIN" "$ROOT/hanna_ui.py" --help \
  > "$OUT_DIR/hanna_ui.help.txt" 2> "$OUT_DIR/hanna_ui.help.err"

run_step "Canonical inventory JSON" \
  "$ROOT/scripts/hanna" ls --json-only --output-file "$OUT_DIR/inventory.json" \
  > "$OUT_DIR/inventory.stdout.txt" 2> "$OUT_DIR/inventory.stderr.txt"

run_step "Canonical preflight JSON" \
  bash -lc "'$ROOT/scripts/hanna' pf --modules full-spectrum --json-only > '$OUT_DIR/preflight.json' 2> '$OUT_DIR/preflight.stderr.txt'"

run_step "Summary schema smoke" \
  "$ROOT/scripts/hanna" sum --target "Prelaunch Smoke" --text "password leaked for user@example.com near військова частина" \
  > "$OUT_DIR/smart-summary.json" 2> "$OUT_DIR/smart-summary.err"

run_step "Focused regression pack" \
  "$PY_BIN" -m pytest \
  "$ROOT/tests/test_exporters.py" \
  "$ROOT/tests/test_legacy_entrypoints.py" \
  "$ROOT/tests/test_run_discovery.py" \
  "$ROOT/tests/test_cli_contracts.py" \
  "$ROOT/tests/test_integration_runtime_smokes.py::test_aggregate_runtime_smoke_tracks_missing_credentials" \
  "$ROOT/tests/test_discovery_engine.py::TestEntityResolution::test_same_business_record_links_push_cluster_confidence_above_threshold" \
  -q > "$OUT_DIR/pytest.txt" 2> "$OUT_DIR/pytest.err"

if [[ "$RUN_LIVE_SMOKE" == "1" ]]; then
  run_step "Optional no-credential chain smoke" \
    env \
      -u OPENAI_API_KEY \
      -u BLACKBIRD_API_KEY \
      -u BLACKBIRD_TOKEN \
      -u ODB_API_KEY \
      -u OPENDATABOT_API_KEY \
      -u SERPAPI_API_KEY \
      -u SHODAN_API_KEY \
      -u CENSYS_API_ID \
      -u CENSYS_API_SECRET \
      "$PY_BIN" "$ROOT/src/cli.py" chain \
      --target prelaunch-smoke \
      --modules full-spectrum \
      --json-summary-only \
      --export-formats metadata \
      --output "$OUT_DIR/live-smoke.html" \
      --no-preflight > "$OUT_DIR/live-smoke.json" 2> "$OUT_DIR/live-smoke.err"
fi

if [[ "$RUN_FULL_REHEARSAL" == "1" ]]; then
  run_step "Optional full rollout rehearsal" \
    env \
      HANNA_FULL_REHEARSAL_TARGET="$FULL_REHEARSAL_TARGET" \
      HANNA_FULL_REHEARSAL_MODULES="$FULL_REHEARSAL_MODULES" \
      HANNA_FULL_REHEARSAL_REPORT_MODE="$FULL_REHEARSAL_REPORT_MODE" \
      bash -lc '
      set -euo pipefail
      if [[ -z "$HANNA_FULL_REHEARSAL_TARGET" ]]; then
        echo "HANNA_FULL_REHEARSAL_TARGET is required when HANNA_RUN_FULL_REHEARSAL=1" >&2
        exit 2
      fi
      "'$ROOT'/scripts/hanna" ch \
        --target "$HANNA_FULL_REHEARSAL_TARGET" \
        --modules "$HANNA_FULL_REHEARSAL_MODULES" \
        --report-mode "$HANNA_FULL_REHEARSAL_REPORT_MODE" \
        --export-formats json,metadata,stix,zip \
        --export-dir "'$OUT_DIR'/rehearsal-artifacts" \
        --metadata-file "'$OUT_DIR'/full-rehearsal.metadata.json" \
        --output "'$OUT_DIR'/full-rehearsal.html" \
        --json-summary-only > "'$OUT_DIR'/full-rehearsal.runtime.json" 2> "'$OUT_DIR'/full-rehearsal.err"
    '

  run_step "Optional rehearsal artifact verification" \
    env PRELAUNCH_OUT_DIR="$OUT_DIR" "$PY_BIN" - <<'PY' > "$OUT_DIR/full-rehearsal.verification.json" 2> "$OUT_DIR/full-rehearsal.verification.err"
import json
import os
from pathlib import Path

out_dir = Path(os.environ["PRELAUNCH_OUT_DIR"])
metadata_path = out_dir / "full-rehearsal.metadata.json"
runtime_path = out_dir / "full-rehearsal.runtime.json"

if not metadata_path.exists():
    raise SystemExit("missing rehearsal metadata export")
if not runtime_path.exists():
    raise SystemExit("missing rehearsal runtime summary")

metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
artifacts = metadata.get("artifacts", {})
exports = artifacts.get("exports", {}) if isinstance(artifacts, dict) else {}
output_path = artifacts.get("output_path") if isinstance(artifacts, dict) else None

required_export_keys = ["json", "stix", "zip"]
missing_keys = [key for key in required_export_keys if key not in exports]
existing = {key: Path(value).exists() for key, value in exports.items()}
html_exists = bool(output_path and Path(output_path).exists())
metadata_exists = metadata_path.exists()

payload = {
  "status": "pass" if metadata_exists and not missing_keys and all(existing.values()) and html_exists else "fail",
    "target_name": metadata.get("target_name"),
    "modules_run": metadata.get("modules_run", []),
    "runtime_summary": runtime,
    "artifacts": {
    "metadata_path": str(metadata_path),
    "metadata_path_exists": metadata_exists,
        "output_path": output_path,
        "output_path_exists": html_exists,
        "exports": exports,
        "existing": existing,
        "missing_export_keys": missing_keys,
    },
}
print(json.dumps(payload, indent=2, ensure_ascii=False))
if payload["status"] != "pass":
    raise SystemExit(1)
PY
fi

generate_final_summary

cat > "$OUT_DIR/README.txt" <<EOF
HANNA pre-launch bundle

Generated: $STAMP
Root: $ROOT

Artifacts:
- run_discovery.list.txt / .err
- hanna_ui.help.txt / .err
- inventory.json
- preflight.json
- status.txt
- smart-summary.json
- final-summary.json
- pytest.txt
$( [[ "$RUN_LIVE_SMOKE" == "1" ]] && printf '%s\n' '- live-smoke.json / .err' )
$( [[ "$RUN_FULL_REHEARSAL" == "1" ]] && printf '%s\n' '- full-rehearsal.runtime.json / .err' )
$( [[ "$RUN_FULL_REHEARSAL" == "1" ]] && printf '%s\n' '- full-rehearsal.metadata.json' )
$( [[ "$RUN_FULL_REHEARSAL" == "1" ]] && printf '%s\n' '- full-rehearsal.verification.json / .err' )

Interpretation:
- Any non-empty *.err should be reviewed.
- preflight.json must not show blocking dependency failures for the intended rollout preset.
- pytest.txt must end with all selected tests passing.
- final-summary.json is the machine-readable verdict for automation and release gates.
EOF

log "Pre-launch check complete"
log "Review bundle: $OUT_DIR"

if [[ "$FAILURES" -ne 0 ]]; then
  log "Pre-launch check recorded $FAILURES failing step(s)"
  exit 1
fi