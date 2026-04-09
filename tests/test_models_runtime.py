from __future__ import annotations

from models import AdapterOutcome, RunResult


def test_run_result_derives_compat_errors_from_outcomes():
    result = RunResult(
        target_name="Case",
        mode="aggregate",
        modules_run=["hibp"],
        outcomes=[
            AdapterOutcome(
                module_name="hibp",
                lane="fast",
                error="missing credentials: HIBP_API_KEY",
                error_kind="missing_credentials",
            )
        ],
    )

    assert result.errors == [{
        "module": "hibp",
        "error": "missing credentials: HIBP_API_KEY",
        "error_kind": "missing_credentials",
    }]
    assert result.runtime_summary()["skipped_missing_credentials"] == 1


def test_run_result_promotes_module_errors_into_outcomes():
    result = RunResult(
        target_name="Case",
        mode="manual",
        modules_run=["ua_leak"],
        outcomes=[AdapterOutcome(module_name="ua_leak", lane="fast")],
        errors=[{"module": "ua_leak", "error": "boom", "error_kind": "adapter_error"}],
    )

    assert result.outcomes[0].error == "boom"
    assert result.outcomes[0].error_kind == "adapter_error"
    assert result.errors == [{"module": "ua_leak", "error": "boom", "error_kind": "adapter_error"}]


def test_run_result_creates_synthetic_outcome_for_error_only_modules():
    result = RunResult(
        target_name="Case",
        mode="aggregate",
        errors=[{"module": "unknown_mod", "error": "Unknown module: unknown_mod", "error_kind": "unknown_module"}],
    )

    assert len(result.outcomes) == 1
    assert result.outcomes[0].module_name == "unknown_mod"
    assert result.outcomes[0].lane == "unknown"
    assert result.errors == [{"module": "unknown_mod", "error": "Unknown module: unknown_mod", "error_kind": "unknown_module"}]