from __future__ import annotations

from preflight import format_preflight_report, has_hard_failures, run_preflight


def test_preflight_returns_named_checks():
    checks = run_preflight()
    names = {check.name for check in checks}
    assert "nuclei" in names
    assert "blackbird" in names
    assert "eyewitness.chrome" in names


def test_preflight_report_contains_summary():
    report = format_preflight_report(run_preflight())
    assert "=== Preflight ===" in report
    assert "Failures:" in report


def test_preflight_can_filter_by_modules():
    checks = run_preflight(modules=["pd-infra"])
    names = {check.name for check in checks}
    assert names == {"nuclei", "katana", "httpx_probe", "naabu"}


def test_has_hard_failures_false_for_current_filtered_pd_infra():
    assert has_hard_failures(run_preflight(modules=["pd-infra"])) is False