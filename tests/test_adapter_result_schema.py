"""
tests/test_adapter_result_schema.py
Tests for src/schemas/adapter_result.py and its CLI integration point.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

import cli as cli_mod
from schemas.adapter_result import AdapterResult, normalize_legacy_payload, validate_result_outcomes


# ---------------------------------------------------------------------------
# AdapterResult model — valid payloads
# ---------------------------------------------------------------------------

class TestAdapterResultValid:
    def test_minimal_required_fields_only(self):
        result = AdapterResult(status="ok")
        assert result.status == "ok"
        assert result.evidence == []
        assert result.observables == []
        assert result.errors == []
        assert result.timings == {}
        assert result.opsec_flags == []

    def test_full_payload_accepted(self):
        result = AdapterResult(
            status="ok",
            evidence=[{"artifact_id": "abc123", "kind": "raw_response"}],
            observables=[{"type": "phone", "value": "+380501234567"}],
            errors=[],
            timings={"elapsed_sec": 1.23, "resolve_sec": 0.5},
            opsec_flags=["no_active_scan"],
        )
        assert result.status == "ok"
        assert result.timings["elapsed_sec"] == pytest.approx(1.23)
        assert result.opsec_flags == ["no_active_scan"]

    def test_error_status_with_error_messages(self):
        result = AdapterResult(status="error", errors=["timeout after 30s"])
        assert result.status == "error"
        assert result.errors == ["timeout after 30s"]

    def test_skipped_status(self):
        result = AdapterResult(status="skipped")
        assert result.status == "skipped"

    def test_extra_fields_ignored(self):
        """extra='ignore' config: unknown keys must not raise."""
        result = AdapterResult(status="ok", legacy_field="should_be_dropped")
        assert not hasattr(result, "legacy_field")


# ---------------------------------------------------------------------------
# AdapterResult model — invalid payloads
# ---------------------------------------------------------------------------

class TestAdapterResultInvalid:
    def test_missing_status_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AdapterResult()

    def test_empty_status_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AdapterResult(status="")

    def test_wrong_type_for_evidence_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AdapterResult(status="ok", evidence="not-a-list")

    def test_wrong_type_for_timings_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AdapterResult(status="ok", timings="not-a-dict")


# ---------------------------------------------------------------------------
# normalize_legacy_payload
# ---------------------------------------------------------------------------

class TestNormalizeLegacyPayload:
    def test_modern_payload_passes_through(self):
        payload = {
            "status": "ok",
            "evidence": [{"kind": "raw"}],
            "observables": [{"type": "phone"}],
            "errors": [],
            "timings": {"elapsed_sec": 0.5},
            "opsec_flags": ["no_active_scan"],
        }
        result = normalize_legacy_payload(payload)
        assert result["status"] == "ok"
        assert result["timings"] == {"elapsed_sec": 0.5}

    def test_legacy_ok_bool_true(self):
        result = normalize_legacy_payload({"ok": True})
        assert result["status"] == "ok"

    def test_legacy_ok_bool_false(self):
        result = normalize_legacy_payload({"ok": False, "error": "timeout"})
        assert result["status"] == "error"
        assert result["errors"] == ["timeout"]

    def test_legacy_hits_mapped_to_evidence(self):
        result = normalize_legacy_payload({"status": "ok", "hits": [{"value": "x"}]})
        assert result["evidence"] == [{"value": "x"}]

    def test_legacy_elapsed_sec_mapped_to_timings(self):
        result = normalize_legacy_payload({"status": "ok", "elapsed_sec": 2.5})
        assert result["timings"] == {"elapsed_sec": 2.5}

    def test_empty_payload_gets_defaults(self):
        result = normalize_legacy_payload({})
        assert result["status"] == "ok"
        assert result["evidence"] == []
        assert result["observables"] == []
        assert result["errors"] == []
        assert result["timings"] == {}
        assert result["opsec_flags"] == []

    def test_error_dict_in_errors_list_coerced_to_string(self):
        result = normalize_legacy_payload({"status": "error", "errors": [{"error": "boom"}]})
        assert result["errors"] == ["boom"]


# ---------------------------------------------------------------------------
# validate_result_outcomes
# ---------------------------------------------------------------------------

class TestValidateResultOutcomes:
    def _make_outcome(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "module_name": "test_module",
            "lane": "fast",
            "hits": [],
            "error": None,
            "error_kind": None,
            "elapsed_sec": 0.1,
            "log_path": "/tmp/test.log",
        }
        base.update(overrides)
        return base

    def test_valid_outcomes_returns_adapter_result_list(self):
        outcomes = [
            self._make_outcome(),
            self._make_outcome(module_name="other_module", lane="slow"),
        ]
        results = validate_result_outcomes(outcomes)
        assert len(results) == 2
        assert all(isinstance(r, AdapterResult) for r in results)

    def test_empty_list_returns_empty(self):
        assert validate_result_outcomes([]) == []

    def test_outcome_with_error_field_still_valid(self):
        outcomes = [self._make_outcome(error="timeout", error_kind="timeout")]
        results = validate_result_outcomes(outcomes)
        assert len(results) == 1
        assert results[0].status == "error"

    def test_non_dict_outcome_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes(["not-a-dict"])
        error = exc_info.value.args[0]
        assert error["failed_count"] == 1
        assert error["validation_errors"][0]["error_type"] == "type_error"

    def test_outcome_missing_status_after_normalization_raises(self):
        """An outcome that normalizes to missing required field raises."""
        # Force a bad normalised dict by patching in an empty string status
        # through an already-normalised dict with empty status
        with pytest.raises(ValueError) as exc_info:
            # Pass status="" directly – normalize_legacy_payload won't be called
            # because we bypass it via injecting a deliberately bad already-processed dict
            # Simulate by passing raw dict with status explicitly ""
            validate_result_outcomes([{"status": ""}])
        error = exc_info.value.args[0]
        assert error["failed_count"] == 1
        assert error["validation_errors"][0]["error_type"] == "validation_error"

    def test_error_object_is_machine_readable(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes([42])
        error = exc_info.value.args[0]
        assert "message" in error
        assert "failed_count" in error
        assert "total_count" in error
        assert "validation_errors" in error

    def test_multiple_failures_reported_together(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes(["bad1", "bad2", self._make_outcome()])
        error = exc_info.value.args[0]
        assert error["failed_count"] == 2
        assert error["total_count"] == 3


# ---------------------------------------------------------------------------
# Integration: _export_result_artifacts rejects malformed outcomes
# ---------------------------------------------------------------------------

class TestExportResultArtifactsIntegration:
    """Verify that _export_result_artifacts fails early when outcomes are malformed."""

    def _make_result_with_outcomes(self, outcomes_raw: list[Any]):
        """Build a minimal fake RunResult-like object with outcomes."""

        class FakeOutcome:
            def __init__(self, raw: dict[str, Any]) -> None:
                self._raw = raw

            def to_dict(self) -> dict[str, Any]:
                return self._raw

        class FakeResult:
            target_name = "Test"
            mode = "manual"
            started_at = "2026-04-08T00:00:00"
            finished_at = "2026-04-08T00:00:01"
            extra: dict[str, Any] = {}
            outcomes = [FakeOutcome(o) if isinstance(o, dict) else o for o in outcomes_raw]

        return FakeResult()

    def test_valid_outcomes_allow_export(self, monkeypatch, tmp_path):
        def _json_export(_result, output_dir):
            path = Path(output_dir) / "result.json"
            path.write_text("{}", encoding="utf-8")
            return path

        monkeypatch.setattr(cli_mod, "export_run_result_json", _json_export)

        result = self._make_result_with_outcomes([
            {"module_name": "ua_phone", "lane": "fast", "hits": [], "error": None, "error_kind": None, "elapsed_sec": 0.5, "log_path": ""},
        ])

        exported = cli_mod._export_result_artifacts(
            result=result,
            export_formats=["json"],
            export_dir=str(tmp_path),
        )
        assert "json" in exported

    def test_malformed_outcomes_abort_export(self):
        """Non-dict outcomes must cause RuntimeError before any file is written."""

        class FakeOutcome:
            def to_dict(self):
                return "not-a-dict"  # broken

        class FakeResult:
            target_name = "Test"
            mode = "manual"
            started_at = "2026-04-08T00:00:00"
            finished_at = "2026-04-08T00:00:01"
            extra: dict[str, Any] = {}
            outcomes = [FakeOutcome()]

        with pytest.raises(RuntimeError, match="Aborting export"):
            cli_mod._export_result_artifacts(
                result=FakeResult(),
                export_formats=["json"],
                export_dir="/tmp",
            )

    def test_empty_export_formats_skips_validation(self):
        """If export_formats is empty, validation is never triggered."""

        class FakeResult:
            outcomes = ["garbage"]  # would fail if validated

        exported = cli_mod._export_result_artifacts(
            result=FakeResult(),
            export_formats=[],
            export_dir=None,
        )
        assert exported == {}
