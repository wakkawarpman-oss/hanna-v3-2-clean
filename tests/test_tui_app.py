from __future__ import annotations

from models import AdapterOutcome, RunResult
from tui.app import HannaTUIApp
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

    app.session_state.pipeline.phase_counters["ingest"] = "total_files=2, ingested=1"
    app.session_state.pipeline.phase_counters["resolve"] = "clusters=3"
    app.session_state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] resolve: clusters=3")

    rendered = app._render_compact_chain_status()

    assert "ingest[total_files=2, ingested=1]" in rendered
    assert "resolve[clusters=3]" in rendered