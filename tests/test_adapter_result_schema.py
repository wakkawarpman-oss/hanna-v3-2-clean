"""tests/test_adapter_result_schema.py

Tests for the AdapterResult schema, normalize_legacy_payload, and
validate_result_outcomes helpers defined in src/schemas/adapter_result.py.

Three test groups:
    1. Valid payload — canonical and legacy shapes are accepted.
    2. Invalid payload — missing/bad fields are rejected with a machine-readable error.
    3. Integration-style — malformed outcomes are rejected at the export boundary
       (_export_result_artifacts) without breaking valid-input behaviour.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from schemas.adapter_result import AdapterResult, normalize_legacy_payload, validate_result_outcomes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outcome_dict(**kwargs) -> dict:
    """Return a minimal valid AdapterResult-compatible dict (canonical shape)."""
    base = {
        "status": "ok",
        "evidence": [],
        "observables": [],
        "errors": [],
        "timings": {"elapsed_sec": 0.5},
        "opsec_flags": [],
    }
    base.update(kwargs)
    return base


# ===========================================================================
# 1. Valid payload tests
# ===========================================================================

class TestValidPayload:
    def test_minimal_canonical_payload(self):
        result = AdapterResult.model_validate({"status": "ok"})
        assert result.status == "ok"
        assert result.evidence == []
        assert result.observables == []
        assert result.errors == []
        assert result.timings == {}
        assert result.opsec_flags == []

    def test_full_canonical_payload(self):
        payload = _make_outcome_dict(
            evidence=[{"kind": "raw_response", "uri": "s3://bucket/artifact.json"}],
            observables=[{"type": "phone", "value": "+380501234567"}],
            errors=[],
            timings={"elapsed_sec": 1.23, "dns_sec": 0.05},
            opsec_flags=["dns_leak"],
        )
        result = AdapterResult.model_validate(payload)
        assert result.status == "ok"
        assert len(result.evidence) == 1
        assert len(result.observables) == 1
        assert result.timings["elapsed_sec"] == 1.23
        assert "dns_leak" in result.opsec_flags

    def test_normalize_legacy_hits_to_observables(self):
        legacy = {
            "status": "ok",
            "hits": [{"type": "email", "value": "x@example.com"}],
        }
        normalised = normalize_legacy_payload(legacy)
        assert "observables" in normalised
        assert "hits" not in normalised
        assert normalised["observables"][0]["value"] == "x@example.com"

    def test_normalize_legacy_error_string_to_errors_list(self):
        legacy = {"status": "error", "error": "timeout after 30s"}
        normalised = normalize_legacy_payload(legacy)
        assert normalised["errors"] == ["timeout after 30s"]

    def test_normalize_legacy_elapsed_sec_to_timings(self):
        legacy = {"status": "ok", "elapsed_sec": 2.5}
        normalised = normalize_legacy_payload(legacy)
        assert normalised["timings"] == {"elapsed_sec": 2.5}

    def test_normalize_legacy_status_aliases(self):
        for alias, expected in [("success", "ok"), ("succeeded", "ok"), ("failure", "error"), ("failed", "error")]:
            normalised = normalize_legacy_payload({"status": alias})
            assert normalised["status"] == expected, f"alias {alias!r} did not map to {expected!r}"

    def test_normalize_derives_status_from_error_field(self):
        """AdapterOutcome.to_dict() shape has no 'status' key."""
        no_status_ok = {"module_name": "ua_phone", "error": None, "hits": [], "elapsed_sec": 0.1}
        no_status_err = {"module_name": "ua_phone", "error": "connection refused", "hits": [], "elapsed_sec": 0.1}
        assert normalize_legacy_payload(no_status_ok)["status"] == "ok"
        assert normalize_legacy_payload(no_status_err)["status"] == "error"

    def test_validate_result_outcomes_returns_list(self):
        outcomes = [_make_outcome_dict(), _make_outcome_dict(status="error", errors=["boom"])]
        validated = validate_result_outcomes(outcomes)
        assert len(validated) == 2
        assert all(isinstance(v, AdapterResult) for v in validated)

    def test_validate_result_outcomes_adapter_outcome_shape(self):
        """Simulate an AdapterOutcome.to_dict() payload (legacy/runtime shape)."""
        raw = {
            "module_name": "ua_phone",
            "lane": "osint",
            "hits": [{"type": "phone", "value": "+380501234567"}],
            "error": None,
            "error_kind": None,
            "elapsed_sec": 0.75,
            "log_path": "/tmp/ua_phone.log",
        }
        validated = validate_result_outcomes([raw])
        assert len(validated) == 1
        assert validated[0].status == "ok"
        assert validated[0].timings["elapsed_sec"] == 0.75


# ===========================================================================
# 2. Invalid payload tests
# ===========================================================================

class TestInvalidPayload:
    def test_missing_status_raises(self):
        with pytest.raises(Exception):
            AdapterResult.model_validate({"evidence": [], "observables": []})

    def test_empty_status_raises(self):
        with pytest.raises(Exception):
            AdapterResult.model_validate({"status": ""})

    def test_validate_result_outcomes_raises_value_error_on_invalid(self):
        bad_outcomes = [{"status": ""}]  # empty string → min_length=1 fails
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes(bad_outcomes)
        err_payload = json.loads(str(exc_info.value))
        assert err_payload["error"] == "validate_result_outcomes_failed"
        assert isinstance(err_payload["failures"], list)
        assert err_payload["failures"][0]["index"] == 0

    def test_validate_result_outcomes_not_a_list_raises(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes({"status": "ok"})  # type: ignore[arg-type]
        err_payload = json.loads(str(exc_info.value))
        assert err_payload["error"] == "validate_result_outcomes_failed"

    def test_validate_result_outcomes_mixed_valid_invalid_raises(self):
        outcomes = [
            _make_outcome_dict(),
            {"status": ""},  # invalid
        ]
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes(outcomes)
        err_payload = json.loads(str(exc_info.value))
        assert any(f["index"] == 1 for f in err_payload["failures"])


# ===========================================================================
# 3. Integration-style: malformed outcomes rejection at export boundary
# ===========================================================================

class TestExportBoundaryIntegration:
    """Verify that _export_result_artifacts rejects malformed outcomes."""

    def _make_mock_result(self, outcomes_dicts: list[dict]) -> MagicMock:
        mock_outcome = MagicMock()
        mock_outcome.to_dict.side_effect = lambda: {}  # will be overridden per outcome
        mock_results = []
        for d in outcomes_dicts:
            mo = MagicMock()
            mo.to_dict.return_value = d
            mock_results.append(mo)

        result = MagicMock()
        result.outcomes = mock_results
        result.extra = {}
        result.target_name = "Test Target"
        result.mode = "aggregate"
        result.started_at = "2026-01-01T00:00:00"
        result.finished_at = "2026-01-01T00:01:00"
        result.modules_run = []
        result.errors = []
        result.runtime_summary.return_value = {}
        return result

    def test_valid_outcomes_do_not_raise_at_export_boundary(self):
        import cli as cli_mod

        valid_outcome = _make_outcome_dict()
        result = self._make_mock_result([valid_outcome])

        with patch("pathlib.Path.mkdir"), \
             patch("cli.export_run_result_json", return_value="/tmp/out.json"):
            exported = cli_mod._export_result_artifacts(result, ["json"], "/tmp/exports")
        assert "json" in exported

    def test_malformed_outcomes_raise_at_export_boundary(self):
        import cli as cli_mod

        bad_outcome = {"status": ""}  # empty string — violates min_length=1
        result = self._make_mock_result([bad_outcome])

        with patch("pathlib.Path.mkdir"):
            with pytest.raises(ValueError) as exc_info:
                cli_mod._export_result_artifacts(result, ["json"], "/tmp/exports")

        err_payload = json.loads(str(exc_info.value))
        assert err_payload["error"] == "validate_result_outcomes_failed"

    def test_no_export_formats_skips_validation(self):
        """Empty export_formats must short-circuit before validation runs."""
        import cli as cli_mod

        bad_outcome = {"status": ""}
        result = self._make_mock_result([bad_outcome])

        # Must not raise because export_formats is empty
        exported = cli_mod._export_result_artifacts(result, [], "/tmp/exports")
        assert exported == {}
