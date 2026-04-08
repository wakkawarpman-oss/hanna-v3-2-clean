from __future__ import annotations

from models import AdapterOutcome, RunResult
from tui.app import HannaTUIApp
from tui.screens import HeatmapPanel, ThreatMeterPanel, validate_editor_payload
from tui.state import apply_editor_updates, apply_run_result, build_default_session_state, clear_pipeline_history, refresh_readiness, reset_modules_for_run, update_module_status, update_phase_counters


def test_build_default_session_state_uses_target_and_report_mode():
    state = build_default_session_state(target="Case Entity", modules=["full-spectrum"], report_mode="strict")

    assert state.target.label == "Case Entity"
    assert state.export.report_mode == "strict"
    assert state.export.formats == ["json", "metadata", "stix", "zip"]
    assert state.execution.export_formats == ["json", "metadata", "stix", "zip"]
    assert state.pipeline.modules
    assert all(module.name != "getcontact" for module in state.pipeline.modules)
    assert state.readiness.checks


def test_build_default_session_state_records_preflight_summary():
    state = build_default_session_state()

    assert state.ops.preflight_failures >= 0
    assert state.ops.preflight_warnings >= 0
    assert state.activity


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
    assert state.target.phones == ["+380500000000"]
    assert state.target.emails == ["case@example.com"]
    assert state.last_result_summary
    assert state.export.html_dir == "/tmp/dossier.html"
    assert any(item.value == "+380500000000" for item in state.observables)


def test_refresh_readiness_rebuilds_check_state():
    state = build_default_session_state(target="Case Entity", modules=["ua_phone"])

    refresh_readiness(state)

    assert state.readiness.checks
    assert state.readiness.secrets_missing or state.readiness.secrets_ready


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

    clear_pipeline_history(state)

    assert state.pipeline.phase == "idle"
    assert state.pipeline.phase_counters == {}
    assert state.pipeline.phase_timeline == []
    assert state.last_result_summary == []


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

    assert "HANNA cockpit active" in banner
    assert "hanna >" in banner
    assert "Press / to refocus input" in banner


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