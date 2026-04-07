from __future__ import annotations

from adapters.base import ReconHit
from scheduler import LaneScheduler
from scheduler import dedup_and_confirm


def test_scheduler_emit_noop_without_callback():
    LaneScheduler._emit(None, {"type": "dispatch_started"})


def test_scheduler_emit_calls_callback():
    events = []

    LaneScheduler._emit(events.append, {"type": "dispatch_started", "task_count": 2})

    assert events == [{"type": "dispatch_started", "task_count": 2}]


def test_dedup_and_confirm_boosts_cross_confirmed_hits():
    h1 = ReconHit(
        observable_type="email",
        value="x@example.com",
        source_module="a",
        source_detail="a",
        confidence=0.4,
    )
    h2 = ReconHit(
        observable_type="email",
        value="x@example.com",
        source_module="b",
        source_detail="b",
        confidence=0.6,
    )

    deduped, cross = dedup_and_confirm([h1, h2])

    assert len(deduped) == 1
    assert len(cross) == 1
    assert cross[0].confidence > 0.6
