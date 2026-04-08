from __future__ import annotations

from preflight import format_preflight_report, has_hard_failures, preflight_summary, run_preflight


def test_preflight_returns_named_checks():
    checks = run_preflight()
    names = {check.name for check in checks}
    assert "nuclei" in names
    assert "blackbird" in names
    assert "eyewitness.chrome" in names
    assert "getcontact_token" in names
    assert "getcontact_aes_key" in names


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


def test_preflight_can_filter_ua_phone_live_requirements():
    checks = run_preflight(modules=["ua_phone"])
    names = {check.name for check in checks}
    assert names == {"telegram_bot_token", "getcontact_token", "getcontact_aes_key"}


def test_preflight_can_filter_getcontact_alias_live_requirements():
    checks = run_preflight(modules=["getcontact"])
    names = {check.name for check in checks}
    assert names == {"telegram_bot_token", "getcontact_token", "getcontact_aes_key"}


def test_preflight_summary_returns_counts_and_checks():
    checks = run_preflight(modules=["ua_phone"])
    payload = preflight_summary(checks, modules=["ua_phone"])

    assert payload["modules"] == ["ua_phone"]
    assert payload["summary"]["total"] == len(checks)
    assert len(payload["checks"]) == len(checks)