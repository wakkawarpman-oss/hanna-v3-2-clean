from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_summary(*, overall_status: str = "pass", failure_count: int = 0) -> dict:
    return {
        "schema_version": 1,
        "bundle_root": "/tmp/prelaunch",
        "generated_from": "scripts/prelaunch_check.sh",
        "overall_status": overall_status,
        "failure_count": failure_count,
        "stage_count": 2,
        "nonempty_error_files": {"count": 0, "files": []},
        "stages": [
            {
                "name": "Stage A",
                "slug": "stage-a",
                "status": "pass",
                "exit_code": 0,
                "started_at": "2026-04-08T00:00:00Z",
                "finished_at": "2026-04-08T00:00:01Z",
            },
            {
                "name": "Stage B",
                "slug": "stage-b",
                "status": "pass" if overall_status == "pass" else "fail",
                "exit_code": 0 if overall_status == "pass" else 1,
                "started_at": "2026-04-08T00:00:01Z",
                "finished_at": "2026-04-08T00:00:02Z",
            },
        ],
        "checks": {
            "preflight": {"status": "pass"},
            "smart_summary": {"status": "pass"},
            "focused_regression": {"status": "pass"},
            "live_smoke": {"enabled": False, "status": "not-run"},
            "full_rollout_rehearsal": {"enabled": False, "status": "not-run"},
        },
    }


def test_validate_summary_accepts_valid_payload():
    module = _load_module(Path(__file__).resolve().parents[1] / "scripts" / "prelaunch_gate.py", "prelaunch_gate_valid")

    errors = module.validate_summary(_sample_summary())

    assert errors == []


def test_validate_summary_rejects_mismatched_failure_count():
    module = _load_module(Path(__file__).resolve().parents[1] / "scripts" / "prelaunch_gate.py", "prelaunch_gate_invalid")

    payload = _sample_summary(overall_status="fail", failure_count=0)
    errors = module.validate_summary(payload)

    assert any("failure_count does not match" in item for item in errors)


def test_build_gate_result_reports_present_checks():
    module = _load_module(Path(__file__).resolve().parents[1] / "scripts" / "prelaunch_gate.py", "prelaunch_gate_result")
    payload = _sample_summary()

    result = module.build_gate_result(Path("/tmp/final-summary.json"), payload, [], required_checks=["full_rollout_rehearsal"])

    assert result["valid"] is True
    assert result["overall_status"] == "pass"
    assert "preflight" in result["checks_present"]
    assert result["required_checks"] == ["full_rollout_rehearsal"]
    assert result["required_check_failures"] == [{
        "check": "full_rollout_rehearsal",
        "reason": "status is 'not-run', expected 'pass'",
    }]


def test_evaluate_required_checks_accepts_rehearsal_pass():
    module = _load_module(Path(__file__).resolve().parents[1] / "scripts" / "prelaunch_gate.py", "prelaunch_gate_required_pass")
    payload = _sample_summary()
    payload["checks"]["full_rollout_rehearsal"] = {"enabled": True, "status": "pass"}

    failures = module.evaluate_required_checks(payload, ["full_rollout_rehearsal"])

    assert failures == []


def test_schema_contract_is_valid_json():
    schema_path = Path(__file__).resolve().parents[1] / "src" / "schemas" / "prelaunch_final_summary.schema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))

    assert payload["$schema"].startswith("https://json-schema.org/")
    assert payload["title"] == "HANNA Prelaunch Final Summary"