"""Shared helpers for orchestration pipelines."""
from __future__ import annotations

from models import RunResult
from runners.aggregate import AggregateRunner


def run_preset(
    preset: str,
    target: str,
    phones: list[str] | None = None,
    usernames: list[str] | None = None,
    proxy: str | None = None,
    leak_dir: str | None = None,
    workers: int = 4,
) -> RunResult:
    runner = AggregateRunner(proxy=proxy, leak_dir=leak_dir, max_workers=workers)
    return runner.run(
        target_name=target,
        known_phones=phones or [],
        known_usernames=usernames or [],
        modules=[preset],
    )
