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


def test_scheduler_timeout_cancellation_state_for_running_future():
    class _RunningFuture:
        def running(self):
            return True

        def cancel(self):
            return False

    state, cancelled = LaneScheduler._timeout_cancellation_state(_RunningFuture())

    assert state == "running_worker_not_reclaimed"
    assert cancelled is False


def test_scheduler_timeout_cancellation_state_for_pending_future():
    class _PendingFuture:
        def running(self):
            return False

        def cancel(self):
            return True

    state, cancelled = LaneScheduler._timeout_cancellation_state(_PendingFuture())

    assert state == "cancelled_before_start"
    assert cancelled is True


def test_scheduler_next_wait_timeout_uses_nearest_deadline():
    class _FutureA:
        pass

    class _FutureB:
        pass

    future_a = _FutureA()
    future_b = _FutureB()
    submitted_at = {future_a: 10.0, future_b: 15.0}
    future_map = {
        future_a: type("Task", (), {"worker_timeout": 20.0})(),
        future_b: type("Task", (), {"worker_timeout": 10.0})(),
    }

    timeout = LaneScheduler._next_wait_timeout({future_a, future_b}, submitted_at, future_map, now=20.0)

    assert timeout == 5.0
