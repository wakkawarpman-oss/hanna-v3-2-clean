from __future__ import annotations

from models import AdapterOutcome, RunResult
from tui.app import HannaTUIApp
from tui.screens import OverviewScreen
from tui.state import build_default_session_state


def test_apply_event_updates_ui_state_transitions(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    app._apply_event({"type": "run_started", "mode": "chain"})
    app._apply_event({"type": "phase", "phase": "ingest", "detail": "ingesting metadata"})
    app._apply_event({"type": "phase_counters", "phase": "ingest", "counters": {"total_files": 2, "ingested": 1}})
    app._apply_event({"type": "module", "module": "httpx_probe", "status": "running", "detail": "worker started"})
    app._apply_event({"type": "activity", "level": "info", "text": "Scheduler active"})

    result = RunResult(
        target_name="Case Entity",
        mode="chain",
        modules_run=["httpx_probe"],
        outcomes=[AdapterOutcome(module_name="httpx_probe", lane="fast")],
        started_at="2026-04-08T01:00:00",
        finished_at="2026-04-08T01:00:05",
        extra={"ingestion": {"ingested": 1, "rejected": 1, "skipped": 0}, "clusters": 2},
    )
    app._apply_event({"type": "run_finished", "result": result})

    assert app.session_state.running is False
    assert app.session_state.pipeline.phase == "completed"
    assert "ingest" in app.session_state.pipeline.phase_counters
    assert app.session_state.pipeline.phase_timeline
    assert any(item.level == "info" and item.text == "Scheduler active" for item in app.session_state.activity)
    assert "Chain:" in app._render_topbar()


def test_render_compact_chain_status_includes_recent_counters():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)
    total_modules = len(app.session_state.pipeline.modules)

    app.session_state.pipeline.phase_counters["ingest"] = "total_files=2, ingested=1"
    app.session_state.pipeline.phase_counters["resolve"] = "clusters=3"
    app.session_state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] resolve: clusters=3")
    app.session_state.pipeline.phase = "resolve"
    app.session_state.pipeline.modules[0].status = "running"

    rendered = app._render_compact_chain_status()

    assert "phase=resolve" in rendered
    assert f"modules done=0/{total_modules} run=1 queue=0 err=0" in rendered
    assert "ingest[total_files=2, ingested=1]" in rendered
    assert "resolve[clusters=3]" in rendered


def test_render_compact_chain_status_shows_module_summary_when_idle():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra", "shodan"], default_mode="chain")
    app = HannaTUIApp(session_state=state)
    total_modules = len(app.session_state.pipeline.modules)

    app.session_state.pipeline.phase = "idle"
    app.session_state.pipeline.modules[0].status = "done"
    app.session_state.pipeline.modules[1].status = "error"

    rendered = app._render_compact_chain_status()

    assert rendered == f"Chain: phase=idle | modules done=1/{total_modules} run=0 queue=0 err=1"


def test_action_clear_timeline_resets_pipeline_history(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    app.session_state.pipeline.phase = "deep_recon"
    app.session_state.pipeline.phase_counters["ingest"] = "total_files=2"
    app.session_state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] ingest: total_files=2")
    app.session_state.last_result_summary = ["summary"]

    app.action_clear_timeline()

    assert app.session_state.pipeline.phase == "idle"
    assert app.session_state.pipeline.phase_counters == {}
    assert app.session_state.pipeline.phase_timeline == []
    assert app.session_state.last_result_summary == []


def test_session_screen_update_state_before_mount_does_not_crash():
    screen = OverviewScreen()
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")

    screen.update_state(state)

    assert screen.session_state is state


def test_action_toggle_rejected_flips_visibility_flag(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    assert app.session_state.show_rejected is False
    app.action_toggle_rejected()
    assert app.session_state.show_rejected is True


def test_command_prompt_run_updates_profile_and_starts_mode(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="idle")
    app = HannaTUIApp(session_state=state)
    started: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_start_run", lambda mode: started.append(mode))

    app._execute_command("run --mode full-spectrum --target 'Ivan Signal' --usernames ivan_ops")

    assert started == ["aggregate"]
    assert app.session_state.execution.target == "Ivan Signal"
    assert "ivan_ops" in app.session_state.execution.known_usernames