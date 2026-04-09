from __future__ import annotations

import os

from models import AdapterOutcome, RunResult
from tui.app import HannaTUIApp
from preflight import PreflightCheck
from tui.screens import HeatmapPanel, ThreatMeterPanel, _build_activity_body, _build_pipeline_body, _build_readiness_body, validate_editor_payload
from tui.state import ActivityEvent, apply_editor_updates, apply_run_result, build_default_session_state, clear_pipeline_history, refresh_readiness, reset_modules_for_run, set_credential_value, toggle_credential_entry, update_module_status, update_phase_counters
from tui.state import ActivityEvent, apply_editor_updates, apply_run_result, build_default_session_state, clear_pipeline_history, credential_env_from_slug, credential_value, refresh_readiness, reset_modules_for_run, set_credential_value, toggle_credential_entry, update_module_status, update_phase_counters


def test_build_default_session_state_uses_target_and_report_mode():
    state = build_default_session_state(target="Case Entity", modules=["full-spectrum"], report_mode="strict")

    assert state.target.label == "Case Entity"
    assert state.export.report_mode == "strict"
    assert state.export.formats == ["json", "metadata", "stix", "zip"]
    assert state.execution.export_formats == ["json", "metadata", "stix", "zip"]
    assert state.pipeline.modules
    assert all(module.name != "getcontact" for module in state.pipeline.modules)
    assert state.readiness.checks
    assert state.locale == "uk"


def test_build_default_session_state_records_preflight_summary():
    state = build_default_session_state()

    assert state.ops.preflight_failures >= 0
    assert state.ops.preflight_warnings >= 0
    assert state.activity
    assert state.credentials


def test_session_credentials_sync_environment(monkeypatch):
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    state = build_default_session_state()

    entry = set_credential_value(state, "SHODAN_API_KEY", "temporary-shodan-key")
    assert entry is not None
    assert entry.value == "temporary-shodan-key"
    assert entry.enabled is False

    toggled = toggle_credential_entry(state, "SHODAN_API_KEY", True)

    assert toggled is not None
    assert toggled.enabled is True
    assert state.readiness.checks
    assert "SHODAN_API_KEY" in os.environ

    toggled = toggle_credential_entry(state, "SHODAN_API_KEY", False)

    assert toggled is not None
    assert toggled.enabled is False
    assert "SHODAN_API_KEY" not in os.environ


def test_reset_modules_for_run_and_status_updates_progress():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"])

    reset_modules_for_run(state, "aggregate", ["httpx_probe", "nuclei"])
    update_module_status(state, "httpx_probe", "done", "2 hit(s)")

    assert state.running is True
    assert state.pipeline.phase == "preparing"
    assert "completed 1/2" in state.pipeline.progress_label


def test_apply_run_result_updates_summary_and_target_data():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"])
    reset_modules_for_run(state, "manual", ["nuclei"])

    result = RunResult(
        target_name="Case Entity",
        mode="manual",
        modules_run=["nuclei"],
        outcomes=[AdapterOutcome(module_name="nuclei", lane="slow")],
        new_phones=["+380500000000"],
        new_emails=["case@example.com"],
        started_at="2026-04-08T01:00:00",
        finished_at="2026-04-08T01:00:05",
        extra={"output_path": "/tmp/dossier.html", "exports": {"json": "/tmp/result.json"}},
    )

    apply_run_result(state, result)

    assert state.running is False
    assert state.prompt_status == "review-ready"
    assert state.target.phones == ["+380500000000"]
    assert state.target.emails == ["case@example.com"]
    assert state.last_result_summary
    assert state.next_actions == ["review", "print", "diagnostics", "new-search", "export-stix", "export-zip"]
    assert state.export.html_dir == "/tmp/dossier.html"
    assert any(item.value == "+380500000000" for item in state.observables)


def test_refresh_readiness_rebuilds_check_state():
    state = build_default_session_state(target="Case Entity", modules=["ua_phone"])

    refresh_readiness(state)

    assert state.readiness.checks
    assert state.readiness.secrets_missing or state.readiness.secrets_ready


def test_credential_slug_reverse_lookup_and_value_reader():
    state = build_default_session_state(target="Case Entity")

    assert credential_env_from_slug("hibp-api-key") == "HIBP_API_KEY"
    assert credential_value(state, "HIBP_API_KEY") == ""


def test_apply_editor_updates_rebuilds_execution_profile():
    state = build_default_session_state(target="Old Entity", modules=["pd-infra"], default_mode="aggregate")

    apply_editor_updates(
        state,
        {
            "target": "New Entity",
            "modules": "ua_phone,nuclei",
            "mode": "manual",
            "manual_module": "ua_phone",
            "phones": "+380500000000,+380501111111",
            "usernames": "caseuser,aliasuser",
            "workers": "6",
            "export_formats": "json,zip",
            "export_dir": "/tmp/artifacts",
            "exports_dir": "/tmp/exports",
            "output_path": "/tmp/dossier.html",
            "report_mode": "strict",
            "verify": "yes",
            "verify_all": "no",
            "verify_content": "yes",
            "no_preflight": "yes",
            "proxy": "socks5h://127.0.0.1:9050",
            "leak_dir": "/tmp/leaks",
        },
    )

    assert state.target.label == "New Entity"
    assert state.execution.default_mode == "manual"
    assert state.execution.manual_module == "ua_phone"
    assert state.execution.resolved_modules == ["ua_phone", "nuclei"]
    assert state.execution.known_phones == ["+380500000000", "+380501111111"]
    assert state.execution.known_usernames == ["caseuser", "aliasuser"]
    assert state.execution.workers == 6
    assert state.execution.export_formats == ["json", "zip"]
    assert state.execution.export_dir == "/tmp/artifacts"
    assert state.execution.exports_dir == "/tmp/exports"
    assert state.execution.output_path == "/tmp/dossier.html"
    assert state.execution.report_mode == "strict"
    assert state.execution.verify is True
    assert state.execution.verify_all is False
    assert state.execution.verify_content is True
    assert state.execution.no_preflight is True
    assert state.execution.proxy == "socks5h://127.0.0.1:9050"
    assert state.execution.leak_dir == "/tmp/leaks"
    assert state.export.report_mode == "strict"
    assert state.export.formats == ["json", "zip"]
    assert len(state.pipeline.modules) == 1
    assert state.pipeline.modules[0].name == "ua_phone"


def test_update_phase_counters_stores_structured_pipeline_details():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"])

    update_phase_counters(state, "ingest", {"total_files": 3, "ingested": 2, "rejected": 1})

    assert "ingest" in state.pipeline.phase_counters
    assert "total_files=3" in state.pipeline.phase_counters["ingest"]
    assert state.pipeline.phase_timeline
    assert "ingest: total_files=3, ingested=2, rejected=1" in state.pipeline.phase_timeline[-1]


def test_clear_pipeline_history_resets_timeline_and_counters():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"])
    update_phase_counters(state, "ingest", {"total_files": 3})
    state.last_result_summary = ["summary"]
    state.next_actions = ["review"]

    clear_pipeline_history(state)

    assert state.pipeline.phase == "idle"
    assert state.pipeline.phase_counters == {}
    assert state.pipeline.phase_timeline == []
    assert state.last_result_summary == []
    assert state.next_actions == []


def test_validate_editor_payload_reports_invalid_values():
    errors = validate_editor_payload(
        {
            "mode": "broken",
            "report_mode": "red",
            "export_formats": "json,xml",
            "workers": "zero",
            "manual_module": "",
            "modules": "",
        }
    )

    assert any("Invalid mode" in item for item in errors)
    assert any("Invalid report mode" in item for item in errors)
    assert any("Invalid export formats" in item for item in errors)
    assert any("Workers must be an integer" in item for item in errors)


def test_validate_editor_payload_accepts_metadata_export_format():
    errors = validate_editor_payload(
        {
            "mode": "aggregate",
            "report_mode": "shareable",
            "export_formats": "json,metadata,stix,zip",
            "workers": "4",
            "manual_module": "",
            "modules": "full-spectrum",
        }
    )

    assert errors == []


def test_tui_startup_banner_explains_internal_prompt():
    app = HannaTUIApp(build_default_session_state(target="Case Entity"))

    banner = app._render_startup_banner()

    assert "Search-first command center active" in banner
    assert "phone, email, username, review" in banner
    assert "Press / to refocus input" in banner


def test_build_pipeline_body_renders_dense_snapshot():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"])
    state.pipeline.phase = "resolve"
    state.pipeline.progress_label = "completed 1/2 | running 1 | queued 0"
    state.pipeline.phase_counters["ingest"] = "total_files=2, ingested=1"
    state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] resolve: clusters=3")
    state.pipeline.modules[0].status = "running"
    state.pipeline.modules[0].detail = "worker started"
    state.next_actions = ["review", "diagnostics"]
    state.last_result_summary = ["=== AGGREGATE Run: Case Entity ===", "Hits: 2"]

    rendered = _build_pipeline_body(state)

    assert "[Pipeline // Live Ops]" in rendered
    assert "phase=resolve" in rendered
    assert "ЛІЧИЛЬНИКИ ФАЗ" in rendered
    assert "СІТКА МОДУЛІВ" in rendered
    assert "next=review, diagnostics" in rendered
    assert "ПІДСУМОК РЕЗУЛЬТАТУ" in rendered


def test_build_readiness_body_renders_gate_snapshot():
    state = build_default_session_state(target="Case Entity", modules=["ua_phone"])
    state.execution.proxy = "socks5h://127.0.0.1:9050"
    state.readiness.checks = [
        PreflightCheck(name="hibp_api_key", status="warn", detail="missing env var"),
        PreflightCheck(name="tor_proxy", status="ok", detail="reachable"),
    ]
    state.readiness.secrets_ready = ["tor_proxy"]
    state.readiness.secrets_missing = ["hibp_api_key"]
    state.readiness.warnings = 1

    rendered = _build_readiness_body(state)

    assert "[Readiness // Gate]" in rendered
    assert "proxy=socks5h://127.0.0.1:9050" in rendered
    assert "СЕКРЕТИ" in rendered
    assert "МАТРИЦЯ ПЕРЕВІРОК" in rendered
    assert "hibp_api_key" in rendered
    assert "tor_proxy" in rendered


def test_refresh_readiness_counts_api_id_credentials(monkeypatch):
    monkeypatch.setenv("CENSYS_API_ID", "test-id")
    monkeypatch.setenv("CENSYS_API_SECRET", "test-secret")

    state = build_default_session_state(target="Case Entity", modules=["censys"])
    refresh_readiness(state)

    assert "censys_api_id" in state.readiness.secrets_ready
    assert "censys_api_secret" in state.readiness.secrets_ready


def test_build_activity_body_renders_dense_console_snapshot():
    state = build_default_session_state(target="Case Entity", modules=["ua_phone"])
    state.pipeline.phase = "aggregate"
    state.running = False
    state.prompt_status = "review-ready"
    state.next_actions = ["review", "print", "diagnostics"]
    state.activity = [
        ActivityEvent(level="info", text="Scheduler active", timestamp="2026-04-08T01:00:00"),
        ActivityEvent(level="ok", text="Aggregate run completed", timestamp="2026-04-08T01:00:03"),
        ActivityEvent(level="warn", text="HIBP key missing", timestamp="2026-04-08T01:00:04"),
    ]

    rendered = _build_activity_body(state)

    assert "[Activity // Live Console]" in rendered
    assert "ПІДСУМОК ПОТОКУ" in rendered
    assert "ОСТАННІ ПОДІЇ" in rendered
    assert "events=3 | info=1 | ok=1 | warn=1 | error=0" in rendered
    assert "next=review, print, diagnostics" in rendered
    assert "Scheduler active" in rendered
    assert "Aggregate run completed" in rendered


def test_heatmap_panel_renders_signal_matrix():
    panel = HeatmapPanel()
    state = build_default_session_state(target="Case Entity")
    payloads: list[str] = []

    panel.update = payloads.append
    panel.render_heatmap(state)

    assert payloads
    assert "SIGNAL HEATMAP" in payloads[0]
    assert "observables=" in payloads[0]


def test_threat_meter_panel_renders_vertical_meter():
    panel = ThreatMeterPanel()
    payloads: list[str] = []

    panel.update = payloads.append
    panel.render_meter(72, "high", 3)

    assert payloads
    assert "THREAT LEVEL" in payloads[0]
    assert "score 072" in payloads[0]
    assert "flags 03" in payloads[0]