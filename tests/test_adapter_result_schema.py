"""Tests for schemas.adapter_result — AdapterResult model and helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schemas.adapter_result import AdapterResult, normalize_legacy_payload, validate_result_outcomes


# ---------------------------------------------------------------------------
# AdapterResult model — valid payloads
# ---------------------------------------------------------------------------

class TestValidAdapterResultPayload:
    def test_minimal_defaults(self):
        result = AdapterResult()
        assert result.status == "ok"
        assert result.evidence == []
        assert result.observables == []
        assert result.errors == []
        assert result.timings == {}
        assert result.opsec_flags == []

    def test_full_payload_accepted(self):
        result = AdapterResult(
            status="ok",
            evidence=[{"kind": "raw_response", "uri": "s3://bucket/file"}],
            observables=[{"type": "phone", "value": "+380501234567"}],
            errors=[],
            timings={"total": 1.23, "dns": 0.05},
            opsec_flags=["tor_exit_detected"],
        )
        assert result.status == "ok"
        assert len(result.evidence) == 1
        assert len(result.observables) == 1
        assert result.timings["total"] == pytest.approx(1.23)
        assert result.opsec_flags == ["tor_exit_detected"]

    def test_error_status_without_errors_auto_fills(self):
        result = AdapterResult(status="error")
        assert result.errors == ["unspecified error"]

    def test_error_status_with_explicit_errors(self):
        result = AdapterResult(status="error", errors=["connection refused"])
        assert result.errors == ["connection refused"]

    def test_timeout_status(self):
        result = AdapterResult(status="timeout")
        assert result.status == "timeout"

    def test_skipped_status(self):
        result = AdapterResult(status="skipped")
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# AdapterResult model — invalid payloads
# ---------------------------------------------------------------------------

class TestInvalidAdapterResultPayload:
    def test_unknown_status_rejected(self):
        with pytest.raises(Exception):
            AdapterResult(status="running")

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            AdapterResult(unknown_field="x")

    def test_errors_must_be_list(self):
        with pytest.raises(Exception):
            AdapterResult(errors={"key": "value"})

    def test_timings_must_be_dict(self):
        with pytest.raises(Exception):
            AdapterResult(timings="fast")


# ---------------------------------------------------------------------------
# normalize_legacy_payload
# ---------------------------------------------------------------------------

class TestNormalizeLegacyPayload:
    def test_empty_dict_yields_safe_defaults(self):
        out = normalize_legacy_payload({})
        assert out["status"] == "ok"
        assert out["evidence"] == []
        assert out["observables"] == []
        assert out["errors"] == []
        assert out["timings"] == {}
        assert out["opsec_flags"] == []

    def test_maps_hits_to_observables(self):
        out = normalize_legacy_payload({"hits": [{"value": "+1234567890"}]})
        assert out["observables"] == [{"value": "+1234567890"}]

    def test_maps_artifacts_to_evidence(self):
        out = normalize_legacy_payload({"artifacts": [{"uri": "s3://x"}]})
        assert out["evidence"] == [{"uri": "s3://x"}]

    def test_maps_timing_to_timings(self):
        out = normalize_legacy_payload({"timing": {"total": 2.0}})
        assert out["timings"] == {"total": 2.0}

    def test_maps_opsec_to_opsec_flags(self):
        out = normalize_legacy_payload({"opsec": ["vpn_detected"]})
        assert out["opsec_flags"] == ["vpn_detected"]

    def test_string_error_coerced_to_list(self):
        out = normalize_legacy_payload({"errors": "something went wrong"})
        assert out["errors"] == ["something went wrong"]

    def test_empty_string_error_coerced_to_empty_list(self):
        out = normalize_legacy_payload({"errors": ""})
        assert out["errors"] == []

    def test_scalar_observables_wrapped_in_dict(self):
        out = normalize_legacy_payload({"observables": ["192.168.1.1", "+380501234567"]})
        assert out["observables"] == [{"value": "192.168.1.1"}, {"value": "+380501234567"}]

    def test_json_string_accepted(self):
        raw = json.dumps({"status": "ok", "hits": [{"value": "x@y.com"}]})
        out = normalize_legacy_payload(raw)
        assert out["observables"] == [{"value": "x@y.com"}]

    def test_invalid_json_string_raises_value_error(self):
        with pytest.raises(ValueError, match="cannot parse JSON string"):
            normalize_legacy_payload("{not valid json}")

    def test_non_dict_non_string_raises_type_error(self):
        with pytest.raises(TypeError, match="expected dict or JSON string"):
            normalize_legacy_payload(42)


# ---------------------------------------------------------------------------
# validate_result_outcomes
# ---------------------------------------------------------------------------

class TestValidateResultOutcomes:
    def test_valid_dict_returns_adapter_result(self):
        result = validate_result_outcomes({"status": "ok", "observables": [{"value": "x"}]})
        assert isinstance(result, AdapterResult)
        assert result.status == "ok"

    def test_already_an_adapter_result_returned_as_is(self):
        original = AdapterResult(status="ok")
        result = validate_result_outcomes(original)
        assert result is original

    def test_invalid_status_raises_value_error_with_json(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes({"status": "running"})
        payload = json.loads(str(exc_info.value))
        assert payload["schema"] == "AdapterResult"
        assert len(payload["errors"]) >= 1

    def test_non_dict_raises_value_error_with_json(self):
        with pytest.raises(ValueError) as exc_info:
            validate_result_outcomes(12345)
        payload = json.loads(str(exc_info.value))
        assert payload["schema"] == "AdapterResult"

    def test_empty_dict_produces_defaults(self):
        result = validate_result_outcomes({})
        assert result.status == "ok"
        assert result.errors == []

    def test_legacy_hits_payload_normalised_and_validated(self):
        result = validate_result_outcomes({"hits": [{"value": "192.0.2.1"}], "timing": {"total": 0.5}})
        assert isinstance(result, AdapterResult)
        assert result.observables == [{"value": "192.0.2.1"}]
        assert result.timings == {"total": 0.5}


# ---------------------------------------------------------------------------
# Integration — malformed payload rejection in export path
# ---------------------------------------------------------------------------

class TestMalformedPayloadRejectionInExport:
    """Simulate the CLI export boundary refusing invalid adapter payloads."""

    def test_malformed_payload_raises_before_export(self, monkeypatch):
        """validate_result_outcomes raises ValueError for malformed input,
        preventing downstream export from ever being reached."""
        export_called = []

        def fake_export(payload):
            export_called.append(payload)

        def export_pipeline(result_dict: dict) -> None:
            validate_result_outcomes(result_dict)
            fake_export(result_dict)

        malformed = {"status": "not_a_valid_status_value"}
        with pytest.raises(ValueError) as exc_info:
            export_pipeline(malformed)

        assert export_called == [], "export must not be called for malformed payload"
        err_payload = json.loads(str(exc_info.value))
        assert err_payload["schema"] == "AdapterResult"

    def test_valid_payload_proceeds_to_export(self):
        export_called = []

        def fake_export(payload):
            export_called.append(payload)

        def export_pipeline(result_dict: dict) -> None:
            validate_result_outcomes(result_dict)
            fake_export(result_dict)

        valid = {"status": "ok", "observables": [{"value": "example.com"}]}
        export_pipeline(valid)
        assert len(export_called) == 1

    def test_cli_export_result_artifacts_validates_run_result(self, monkeypatch, tmp_path):
        """_export_result_artifacts calls validate_result_outcomes for RunResult-like objects."""
        import cli as cli_mod
        from models import RunResult

        validated = []
        original_fn = cli_mod.validate_result_outcomes

        def spy_validate(payload):
            validated.append(payload)
            return original_fn(payload)

        monkeypatch.setattr(cli_mod, "validate_result_outcomes", spy_validate)
        monkeypatch.setattr(cli_mod, "export_run_result_json", lambda r, d: tmp_path / "result.json")
        (tmp_path / "result.json").write_text("{}", encoding="utf-8")

        result = RunResult(
            target_name="Case",
            mode="manual",
            started_at="2026-04-08T00:00:00",
            finished_at="2026-04-08T00:00:01",
            extra={"queued_modules": ["nuclei"]},
        )

        cli_mod._export_result_artifacts(
            result=result,
            export_formats=["json"],
            export_dir=str(tmp_path),
        )

        assert len(validated) == 1, "validate_result_outcomes must be called once for a RunResult"
