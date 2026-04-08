#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "src" / "schemas" / "prelaunch_final_summary.schema.json"
KNOWN_CHECKS = (
    "preflight",
    "smart_summary",
    "focused_regression",
    "live_smoke",
    "full_rollout_rehearsal",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"summary file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in summary file: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("summary root must be a JSON object")
    return payload


def _expect(payload: dict[str, Any], key: str, typ: type, errors: list[str]) -> Any:
    if key not in payload:
        errors.append(f"missing top-level field: {key}")
        return None
    value = payload[key]
    if not isinstance(value, typ):
        errors.append(f"field {key} must be {typ.__name__}")
        return None
    return value


def _validate_stage(stage: Any, index: int, errors: list[str]) -> None:
    if not isinstance(stage, dict):
        errors.append(f"stages[{index}] must be an object")
        return
    for field in ("name", "slug", "status", "exit_code", "started_at", "finished_at"):
        if field not in stage:
            errors.append(f"stages[{index}] missing field: {field}")
    status = stage.get("status")
    if status not in {"pass", "fail"}:
        errors.append(f"stages[{index}].status must be pass or fail")
    exit_code = stage.get("exit_code")
    if not isinstance(exit_code, int) or exit_code < 0:
        errors.append(f"stages[{index}].exit_code must be a non-negative integer")


def validate_summary(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    schema_version = _expect(payload, "schema_version", int, errors)
    if schema_version is not None and schema_version != 1:
        errors.append("schema_version must be 1")

    overall_status = _expect(payload, "overall_status", str, errors)
    if overall_status is not None and overall_status not in {"pass", "fail"}:
        errors.append("overall_status must be pass or fail")

    failure_count = _expect(payload, "failure_count", int, errors)
    if failure_count is not None and failure_count < 0:
        errors.append("failure_count must be >= 0")

    stage_count = _expect(payload, "stage_count", int, errors)
    if stage_count is not None and stage_count < 0:
        errors.append("stage_count must be >= 0")

    _expect(payload, "bundle_root", str, errors)
    _expect(payload, "generated_from", str, errors)

    stages = _expect(payload, "stages", list, errors)
    if isinstance(stages, list):
        for index, stage in enumerate(stages):
            _validate_stage(stage, index, errors)
        if stage_count is not None and stage_count != len(stages):
            errors.append("stage_count does not match number of stages")
        computed_failures = sum(1 for stage in stages if isinstance(stage, dict) and stage.get("status") != "pass")
        if failure_count is not None and failure_count != computed_failures:
            errors.append("failure_count does not match failing stage count")
        if overall_status is not None:
            expected_status = "pass" if computed_failures == 0 else "fail"
            if overall_status != expected_status:
                errors.append("overall_status does not match stage statuses")

    checks = _expect(payload, "checks", dict, errors)
    if isinstance(checks, dict):
        required_checks = set(KNOWN_CHECKS)
        missing = sorted(required_checks.difference(checks))
        for item in missing:
            errors.append(f"checks missing section: {item}")

        for check_name in sorted(required_checks.intersection(checks)):
            check_payload = checks.get(check_name)
            if not isinstance(check_payload, dict):
                errors.append(f"checks.{check_name} must be an object")
                continue
            status = check_payload.get("status")
            if not isinstance(status, str):
                errors.append(f"checks.{check_name}.status must be a string")

    nonempty_error_files = _expect(payload, "nonempty_error_files", dict, errors)
    if isinstance(nonempty_error_files, dict):
        count = nonempty_error_files.get("count")
        files = nonempty_error_files.get("files")
        if not isinstance(count, int) or count < 0:
            errors.append("nonempty_error_files.count must be a non-negative integer")
        if not isinstance(files, list):
            errors.append("nonempty_error_files.files must be an array")

    return errors


def evaluate_required_checks(payload: dict[str, Any], required_checks: list[str]) -> list[dict[str, str]]:
    checks = payload.get("checks", {}) if isinstance(payload.get("checks"), dict) else {}
    failures: list[dict[str, str]] = []
    for check_name in required_checks:
        check_payload = checks.get(check_name)
        if not isinstance(check_payload, dict):
            failures.append({
                "check": check_name,
                "reason": "missing check payload",
            })
            continue
        status = check_payload.get("status")
        if status != "pass":
            failures.append({
                "check": check_name,
                "reason": f"status is {status!r}, expected 'pass'",
            })
    return failures


def build_gate_result(summary_path: Path, payload: dict[str, Any], errors: list[str], required_checks: list[str] | None = None) -> dict[str, Any]:
    checks = payload.get("checks", {}) if isinstance(payload.get("checks"), dict) else {}
    required = list(required_checks or [])
    required_failures = evaluate_required_checks(payload, required)
    return {
        "summary_path": str(summary_path),
        "schema_path": str(DEFAULT_SCHEMA),
        "schema_version": payload.get("schema_version"),
        "overall_status": payload.get("overall_status"),
        "failure_count": payload.get("failure_count"),
        "stage_count": payload.get("stage_count"),
        "checks_present": sorted(checks.keys()) if isinstance(checks, dict) else [],
        "required_checks": required,
        "required_check_failures": required_failures,
        "valid": not errors,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate HANNA prelaunch final-summary.json for CI gates")
    parser.add_argument("summary_file", help="Path to final-summary.json")
    parser.add_argument("--schema-file", default=str(DEFAULT_SCHEMA), help="Documented schema contract path for traceability")
    parser.add_argument("--allow-fail", action="store_true", help="Exit zero even if overall_status is fail, as long as schema validation succeeds")
    parser.add_argument(
        "--require-check",
        action="append",
        dest="required_checks",
        choices=KNOWN_CHECKS,
        default=[],
        help="Require a specific checks.<name>.status to be 'pass'. May be provided multiple times.",
    )
    parser.add_argument("--json-only", action="store_true", help="Print only gate result JSON")
    args = parser.parse_args()

    summary_path = Path(args.summary_file)
    schema_path = Path(args.schema_file)
    payload = _load_json(summary_path)
    errors = validate_summary(payload)
    gate_result = build_gate_result(summary_path, payload, errors, required_checks=args.required_checks)
    gate_result["schema_path"] = str(schema_path)

    body = json.dumps(gate_result, ensure_ascii=False, indent=None if args.json_only else 2)
    print(body)

    if errors:
        sys.exit(2)
    if gate_result["required_check_failures"]:
        sys.exit(1)
    if not args.allow_fail and payload.get("overall_status") != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()