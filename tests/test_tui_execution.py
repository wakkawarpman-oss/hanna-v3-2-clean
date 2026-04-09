from __future__ import annotations

import json
from pathlib import Path

from adapters.base import ReconHit, ReconReport
from scheduler import SchedulerResult
from tui.execution import TUIExecutionConfig, run_mode


def test_run_mode_manual_emits_expected_events(monkeypatch):
    import tui.execution as execution_mod

    class StubAdapter:
        region = "global"

        def __init__(self, proxy=None, timeout=0.0, leak_dir=None):
            self.proxy = proxy
            self.timeout = timeout
            self.leak_dir = leak_dir

        def search(self, target_name, known_phones, known_usernames):
            return [
                ReconHit(
                    observable_type="email",
                    value="stub@example.com",
                    source_module="stub_manual",
                    source_detail="fixture",
                    confidence=0.8,
                )
            ]

    monkeypatch.setattr(execution_mod, "run_preflight", lambda modules=None: [])
    monkeypatch.setitem(execution_mod.MODULES, "stub_manual", StubAdapter)

    events: list[dict] = []
    result = run_mode(
        TUIExecutionConfig(target="Case", manual_module="stub_manual", modules=["stub_manual"]),
        "manual",
        events.append,
    )

    event_types = [event["type"] for event in events]
    assert result.mode == "manual"
    assert "run_started" in event_types
    assert "modules_resolved" in event_types
    assert "readiness" in event_types
    assert "phase" in event_types
    assert sum(1 for event in events if event["type"] == "module") >= 2
    assert not any("Exported artifacts" in event.get("text", "") for event in events if event["type"] == "activity")
    assert event_types[-1] == "run_finished"


def test_run_mode_aggregate_emits_scheduler_driven_module_events(monkeypatch):
    import tui.execution as execution_mod

    hit = ReconHit(
        observable_type="phone",
        value="+380500000000",
        source_module="stub_aggregate",
        source_detail="fixture",
        confidence=0.7,
    )

    monkeypatch.setattr(execution_mod, "run_preflight", lambda modules=None: [])
    monkeypatch.setattr(execution_mod, "build_tasks", lambda *args, **kwargs: ([], []))

    def _dispatch(**kwargs):
        callback = kwargs.get("event_callback")
        callback({"type": "lane_started", "lane": "fast", "task_count": 1})
        callback({"type": "task_queued", "lane": "fast", "module": "stub_aggregate", "priority": 1})
        callback({"type": "task_done", "lane": "fast", "module": "stub_aggregate", "hit_count": 1, "elapsed_sec": 0.1})
        callback({"type": "lane_complete", "lane": "fast", "ok_count": 1, "task_count": 1})
        return SchedulerResult(all_hits=[hit], modules_run=["stub_aggregate"], errors=[], task_results=[])

    monkeypatch.setattr(execution_mod.LaneScheduler, "dispatch", _dispatch)

    events: list[dict] = []
    result = run_mode(
        TUIExecutionConfig(target="Case", modules=["stub_aggregate"]),
        "aggregate",
        events.append,
    )

    assert result.mode == "aggregate"
    module_events = [event for event in events if event["type"] == "module"]
    assert any(event["status"] == "queued" for event in module_events)
    assert any(event["status"] == "done" for event in module_events)
    assert any(event["type"] == "activity" and "fast complete" in event["text"] for event in events)
    assert "exports" not in result.extra


def test_run_mode_chain_emits_detailed_phase_counters(monkeypatch, tmp_path):
    import tui.execution as execution_mod

    class FakeDB:
        def execute(self, *args, **kwargs):
            return self

        def commit(self):
            return None

    class FakeEngine:
        def __init__(self, db_path):
            self.db_path = db_path
            self.db = FakeDB()
            self._all_observables = []
            self.clusters = []

        def ingest_metadata(self, path):
            if Path(path).name == "source.json":
                return {"status": "ingested"}
            return {"status": "rejected"}

        def resolve_entities(self):
            self.clusters = [type("Cluster", (), {"label": "Case Cluster"})()]
            return self.clusters

        def verify_profiles(self, max_checks, timeout, proxy=None):
            return None

        def verify_content(self, max_checks, timeout, proxy=None):
            return None

        def render_graph_report(self, output_path, redaction_mode="shareable"):
            Path(output_path).write_text("ok", encoding="utf-8")

        def get_stats(self):
            return {"ok": True}

        def _classify_and_register(self, **kwargs):
            return object()

    report = ReconReport(
        target_name="Case",
        modules_run=["stub_chain"],
        hits=[
            ReconHit(
                observable_type="email",
                value="chain@example.com",
                source_module="stub_chain",
                source_detail="fixture",
                confidence=0.8,
            )
        ],
        errors=[],
        started_at="2026-04-08T01:00:00",
        finished_at="2026-04-08T01:00:01",
        new_emails=["chain@example.com"],
    )

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "source.json").write_text(
        json.dumps(
            {
                "target": "+380991234598",
                "profile": "phone",
                "status": "success",
                "log_file": "/tmp/source.log",
            }
        ),
        encoding="utf-8",
    )
    (exports_dir / "generated.chain.metadata.json").write_text(
        json.dumps({"runtime_summary": {"mode": "chain"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(execution_mod, "DiscoveryEngine", FakeEngine)
    monkeypatch.setattr(execution_mod, "run_preflight", lambda modules=None: [])
    monkeypatch.setattr(execution_mod, "_run_deep_recon_live", lambda engine, config, modules, event_sink: report)

    events: list[dict] = []
    result = run_mode(
        TUIExecutionConfig(
            target="Case",
            modules=["stub_chain"],
            exports_dir=str(exports_dir),
            db_path=str(tmp_path / "discovery.db"),
            verify=True,
            verify_content=True,
        ),
        "chain",
        events.append,
    )

    assert result.mode == "chain"
    counter_events = [event for event in events if event["type"] == "phase_counters"]
    phases = {event["phase"] for event in counter_events}
    assert {"ingest", "resolve", "deep_recon", "verify_profiles", "verify_content", "render"}.issubset(phases)
    ingest_updates = [event for event in counter_events if event["phase"] == "ingest"]
    assert any(event["counters"].get("total_files") == 1 for event in ingest_updates)
    assert any(event["counters"].get("ingested") == 1 for event in ingest_updates)
    assert "exports" not in result.extra