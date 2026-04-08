from __future__ import annotations

from adapters.base import ReconHit
from runners.aggregate import AggregateRunner
from scheduler import SchedulerResult


def test_aggregate_runner_dedup_and_cross_confirm(monkeypatch):
    import runners.aggregate as aggregate_mod

    hit_a = ReconHit(
        observable_type="url",
        value="https://example.com",
        source_module="mod_a",
        source_detail="a",
        confidence=0.4,
    )
    hit_b = ReconHit(
        observable_type="url",
        value="https://example.com",
        source_module="mod_b",
        source_detail="b",
        confidence=0.6,
    )

    monkeypatch.setattr(aggregate_mod, "build_tasks", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(
        aggregate_mod.LaneScheduler,
        "dispatch",
        lambda **kwargs: SchedulerResult(all_hits=[hit_a, hit_b], modules_run=["mod_a", "mod_b"], errors=[], task_results=[]),
    )

    runner = AggregateRunner()
    result = runner.run(target_name="target", modules=["mod_a", "mod_b"])

    assert len(result.all_hits) == 1
    assert len(result.cross_confirmed) == 1
    assert result.cross_confirmed[0].confidence > 0.6
    assert result.runtime_summary()["queued"] == 2
    assert result.runtime_summary()["completed"] == 0


def test_aggregate_runner_runtime_summary_tracks_timeouts(monkeypatch):
    import runners.aggregate as aggregate_mod
    from worker import TaskResult

    monkeypatch.setattr(aggregate_mod, "build_tasks", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(
        aggregate_mod.LaneScheduler,
        "dispatch",
        lambda **kwargs: SchedulerResult(
            all_hits=[],
            modules_run=["mod_timeout"],
            errors=[{"module": "mod_timeout", "error": "TIMEOUT (60s)", "error_kind": "timeout"}],
            task_results=[TaskResult(module_name="mod_timeout", lane="fast", hits=[], error="TIMEOUT (60s)", error_kind="timeout", elapsed_sec=60.0, raw_log_path="")],
        ),
    )

    runner = AggregateRunner()
    result = runner.run(target_name="target", modules=["mod_timeout"])

    summary = result.runtime_summary()
    assert summary["queued"] == 1
    assert summary["timed_out"] == 1
    assert summary["failed"] == 0
