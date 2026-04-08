"""
test_adapter_result_schema.py — focused tests for the AdapterResult schema contract.

Covers:
    1. Valid contract payload round-trips through Pydantic.
    2. Invalid contract payload raises ValidationError with useful details.
    3. normalize_legacy_payload correctly converts legacy AdapterOutcome dicts.
    4. validate_adapter_outcomes raises AdapterPayloadValidationError on
       malformed outcomes (integration-level export-boundary test).
    5. cli._export_result_artifacts propagates validation errors before writing
       any file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import cli as cli_mod
from models import AdapterOutcome, RunResult
from adapters.base import ReconHit
from schemas import (
    AdapterPayloadValidationError,
    AdapterResult,
    AdapterResultStatus,
    EvidenceItem,
    ObservableItem,
    OpsecFlag,
    TimingInfo,
    normalize_legacy_payload,
    validate_adapter_outcomes,
)


# ---------------------------------------------------------------------------
# 1. Valid contract payload
# ---------------------------------------------------------------------------

class TestAdapterResultValidPayload:
    def test_minimal_ok_payload(self):
        result = AdapterResult.model_validate({"status": "ok"})
        assert result.status == AdapterResultStatus.OK
        assert result.evidence == []
        assert result.observables == []
        assert result.errors == []
        assert result.timings.elapsed_sec == 0.0
        assert result.opsec_flags == []

    def test_full_payload(self):
        payload = {
            "status": "error",
            "evidence": [{"kind": "execution_log", "uri": "/tmp/adapter.log"}],
            "observables": [
                {
                    "observable_type": "phone",
                    "value": "+380501234567",
                    "source_module": "ua_phone",
                    "confidence": 0.9,
                }
            ],
            "errors": ["connection refused"],
            "timings": {
                "elapsed_sec": 3.14,
                "started_at": "2026-04-08T00:00:00",
                "finished_at": "2026-04-08T00:00:03",
            },
            "opsec_flags": [{"flag": "clearnet_request", "severity": "low"}],
        }
        result = AdapterResult.model_validate(payload)
        assert result.status == AdapterResultStatus.ERROR
        assert result.timings.elapsed_sec == pytest.approx(3.14)
        assert result.observables[0].value == "+380501234567"
        assert result.evidence[0].kind == "execution_log"
        assert result.opsec_flags[0].flag == "clearnet_request"

    def test_timeout_and_skipped_statuses_are_valid(self):
        for status in ("timeout", "skipped"):
            result = AdapterResult.model_validate({"status": status})
            assert result.status.value == status

    def test_extra_fields_are_preserved(self):
        """extra='allow' means unknown keys should pass through."""
        result = AdapterResult.model_validate({"status": "ok", "custom_field": 42})
        assert result.model_extra["custom_field"] == 42


# ---------------------------------------------------------------------------
# 2. Invalid contract payload
# ---------------------------------------------------------------------------

class TestAdapterResultInvalidPayload:
    def test_missing_status_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            AdapterResult.model_validate({})
        errors = exc_info.value.errors(include_url=False)
        fields = {e["loc"][0] for e in errors}
        assert "status" in fields

    def test_invalid_status_string_raises(self):
        with pytest.raises(ValidationError):
            AdapterResult.model_validate({"status": "running"})

    def test_negative_elapsed_sec_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            AdapterResult.model_validate(
                {"status": "ok", "timings": {"elapsed_sec": -0.1}}
            )
        errors = exc_info.value.errors(include_url=False)
        assert any("elapsed_sec" in str(e["loc"]) for e in errors)

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            AdapterResult.model_validate(
                {
                    "status": "ok",
                    "observables": [
                        {
                            "observable_type": "phone",
                            "value": "+380501234567",
                            "confidence": 1.5,  # > 1.0
                        }
                    ],
                }
            )

    def test_invalid_evidence_missing_kind_raises(self):
        with pytest.raises(ValidationError):
            AdapterResult.model_validate(
                {"status": "ok", "evidence": [{"uri": "/tmp/log"}]}  # missing kind
            )


# ---------------------------------------------------------------------------
# 3. normalize_legacy_payload
# ---------------------------------------------------------------------------

class TestNormalizeLegacyPayload:
    def _ok_outcome_dict(self) -> dict:
        return {
            "module_name": "ua_phone",
            "lane": "fast",
            "hits": [
                {
                    "observable_type": "phone",
                    "value": "+380501234567",
                    "source_module": "ua_phone",
                    "source_detail": "yandex_food_leak",
                    "confidence": 0.85,
                }
            ],
            "error": None,
            "error_kind": None,
            "elapsed_sec": 1.23,
            "log_path": "/tmp/ua_phone.log",
        }

    def test_ok_outcome_maps_to_ok_status(self):
        normalized = normalize_legacy_payload(self._ok_outcome_dict())
        assert normalized["status"] == "ok"

    def test_observables_extracted_from_hits(self):
        normalized = normalize_legacy_payload(self._ok_outcome_dict())
        assert len(normalized["observables"]) == 1
        obs = normalized["observables"][0]
        assert obs["value"] == "+380501234567"
        assert obs["source_module"] == "ua_phone"
        assert obs["confidence"] == pytest.approx(0.85)

    def test_evidence_extracted_from_log_path(self):
        normalized = normalize_legacy_payload(self._ok_outcome_dict())
        assert normalized["evidence"] == [
            {"kind": "execution_log", "uri": "/tmp/ua_phone.log"}
        ]

    def test_timings_extracted(self):
        normalized = normalize_legacy_payload(self._ok_outcome_dict())
        assert normalized["timings"]["elapsed_sec"] == pytest.approx(1.23)

    def test_error_outcome_maps_to_error_status(self):
        raw = {
            "module_name": "nuclei",
            "error": "connection refused",
            "error_kind": "adapter_error",
            "elapsed_sec": 0.5,
            "hits": [],
            "log_path": "",
        }
        normalized = normalize_legacy_payload(raw)
        assert normalized["status"] == "error"
        assert normalized["errors"] == ["connection refused"]

    def test_timeout_error_kind_maps_to_timeout_status(self):
        raw = {"module_name": "nmap", "error": "timed out", "error_kind": "timeout", "hits": []}
        assert normalize_legacy_payload(raw)["status"] == "timeout"

    def test_missing_credentials_maps_to_skipped(self):
        raw = {"module_name": "shodan", "error": "missing api key", "error_kind": "missing_credentials", "hits": []}
        assert normalize_legacy_payload(raw)["status"] == "skipped"

    def test_missing_binary_maps_to_skipped(self):
        raw = {"module_name": "amass", "error": "missing binary: amass", "error_kind": "missing_binary", "hits": []}
        assert normalize_legacy_payload(raw)["status"] == "skipped"

    def test_already_canonical_payload_passes_through(self):
        canonical = {"status": "ok", "evidence": [], "observables": [], "errors": [], "timings": {"elapsed_sec": 0}}
        result = normalize_legacy_payload(canonical)
        assert result["status"] == "ok"

    def test_normalized_payload_passes_pydantic_validation(self):
        normalized = normalize_legacy_payload(self._ok_outcome_dict())
        result = AdapterResult.model_validate(normalized)
        assert result.status == AdapterResultStatus.OK


# ---------------------------------------------------------------------------
# 4. validate_adapter_outcomes — bulk validation
# ---------------------------------------------------------------------------

class TestValidateAdapterOutcomes:
    def _make_outcome(self, **kwargs) -> AdapterOutcome:
        defaults = dict(
            module_name="ua_phone",
            lane="fast",
            hits=[],
            elapsed_sec=1.0,
        )
        defaults.update(kwargs)
        return AdapterOutcome(**defaults)

    def test_valid_outcomes_do_not_raise(self):
        outcomes = [
            self._make_outcome(module_name="ua_phone"),
            self._make_outcome(module_name="nuclei", error="connection refused", error_kind="adapter_error"),
            self._make_outcome(module_name="shodan", error="missing api key", error_kind="missing_credentials"),
        ]
        # Should not raise
        validate_adapter_outcomes(outcomes)

    def test_empty_list_does_not_raise(self):
        validate_adapter_outcomes([])

    def test_malformed_dict_raises_adapter_payload_validation_error(self):
        """A raw dict with elapsed_sec < 0 must fail after normalization."""
        malformed = {
            "module_name": "bad_adapter",
            "status": "ok",  # already canonical — normalize passes through
            "timings": {"elapsed_sec": -1.0},  # violates ge=0
        }
        with pytest.raises(AdapterPayloadValidationError) as exc_info:
            validate_adapter_outcomes([malformed])
        err = exc_info.value
        assert err.failures[0]["module"] == "bad_adapter"
        assert any("elapsed_sec" in str(ve["loc"]) for ve in err.failures[0]["validation_errors"])

    def test_multiple_failures_are_aggregated(self):
        bad1 = {"module_name": "alpha", "status": "unknown_status"}
        bad2 = {"module_name": "beta", "status": "also_bad"}
        with pytest.raises(AdapterPayloadValidationError) as exc_info:
            validate_adapter_outcomes([bad1, bad2])
        err = exc_info.value
        assert len(err.failures) == 2
        modules = {f["module"] for f in err.failures}
        assert modules == {"alpha", "beta"}

    def test_error_is_json_serialisable(self):
        malformed = {"module_name": "bad", "status": "nope"}
        with pytest.raises(AdapterPayloadValidationError) as exc_info:
            validate_adapter_outcomes([malformed])
        # The str() form should be valid JSON after the first line
        body = str(exc_info.value).split("\n", 1)[1]
        parsed = json.loads(body)
        assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# 5. Integration: cli._export_result_artifacts rejects malformed outcomes
# ---------------------------------------------------------------------------

class TestExportResultArtifactsValidation:
    def _make_run_result(self, outcomes: list[AdapterOutcome]) -> RunResult:
        return RunResult(
            target_name="Case",
            mode="aggregate",
            started_at="2026-04-08T00:00:00",
            finished_at="2026-04-08T00:00:01",
            outcomes=outcomes,
            extra={"queued_modules": [o.module_name for o in outcomes]},
        )

    def test_valid_outcomes_allow_export(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            cli_mod,
            "export_run_result_json",
            lambda result, output_dir: (tmp_path / "result.json").write_text("{}")
            or (tmp_path / "result.json"),
        )
        result = self._make_run_result(
            [AdapterOutcome(module_name="ua_phone", lane="fast", elapsed_sec=1.0)]
        )
        exported = cli_mod._export_result_artifacts(
            result=result,
            export_formats=["json"],
            export_dir=str(tmp_path),
        )
        assert "json" in exported

    def test_malformed_outcome_blocks_export(self, tmp_path):
        """An outcome dict with invalid timings must raise before any file is written."""
        result = RunResult(
            target_name="Case",
            mode="aggregate",
            started_at="2026-04-08T00:00:00",
            finished_at="2026-04-08T00:00:01",
            extra={"queued_modules": ["bad_adapter"]},
        )
        # Inject a raw-dict-style outcome that has no to_dict() but is invalid
        bad_outcome = {"module_name": "bad_adapter", "status": "ok", "timings": {"elapsed_sec": -5.0}}
        result.outcomes = [bad_outcome]  # type: ignore[assignment]

        with pytest.raises(AdapterPayloadValidationError):
            cli_mod._export_result_artifacts(
                result=result,
                export_formats=["json"],
                export_dir=str(tmp_path),
            )

        # No files should have been written
        assert list(tmp_path.iterdir()) == []

    def test_no_export_formats_skips_validation(self, tmp_path):
        """When export_formats is empty, validation is skipped (nothing to do)."""
        result = RunResult(
            target_name="Case",
            mode="aggregate",
            started_at="2026-04-08T00:00:00",
            finished_at="2026-04-08T00:00:01",
        )
        result.outcomes = [{"module_name": "bad", "status": "nope"}]  # type: ignore[assignment]
        exported = cli_mod._export_result_artifacts(
            result=result,
            export_formats=[],
            export_dir=str(tmp_path),
        )
        assert exported == {}
