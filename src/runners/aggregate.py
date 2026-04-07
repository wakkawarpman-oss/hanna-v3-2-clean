"""
runners.aggregate — One-shot parallel execution across multiple adapters.

Dispatches selected adapters in a lane-priority worker pool (Fast → Slow,
P0 → P3), deduplicates hits, tags cross-confirmed observables, and returns
a unified RunResult.

Usage:
    runner = AggregateRunner(proxy="socks5h://127.0.0.1:9050")
    result = runner.run(
        target_name="Hanna Dosenko",
        known_phones=["+380507133698"],
        modules=["ua_leak", "ru_leak", "ghunt"],
    )
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from adapters.base import ReconHit
from config import RUNS_ROOT
from models import AdapterOutcome, RunResult
from registry import resolve_modules
from scheduler import LaneScheduler, dedup_and_confirm
from worker import build_tasks


class AggregateRunner:
    """Parallel one-shot runner. Fires all requested adapters at once."""

    def __init__(
        self,
        proxy: str | None = None,
        timeout: float = 10.0,
        leak_dir: str | None = None,
        max_workers: int = 4,
        log_dir: str | None = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.leak_dir = leak_dir
        self.max_workers = max_workers
        self.log_dir = log_dir or str(RUNS_ROOT / "logs")

    def run(
        self,
        target_name: str,
        known_phones: list[str] | None = None,
        known_usernames: list[str] | None = None,
        modules: list[str] | None = None,
    ) -> RunResult:
        known_phones = known_phones or []
        known_usernames = known_usernames or []
        module_names = resolve_modules(modules)

        tasks, errors = build_tasks(
            module_names, target_name, known_phones, known_usernames,
            self.proxy, self.timeout, self.leak_dir,
        )

        started = datetime.now().isoformat()
        all_hits: list[ReconHit] = []
        modules_run: list[str] = []
        outcomes: list[AdapterOutcome] = []

        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        scheduled = LaneScheduler.dispatch(tasks=tasks, max_workers=self.max_workers, log_dir=self.log_dir, label="aggregate")
        errors.extend(scheduled.errors)
        modules_run = scheduled.modules_run
        all_hits = scheduled.all_hits
        for tr in scheduled.task_results:
            outcomes.append(AdapterOutcome(
                module_name=tr.module_name,
                lane=tr.lane,
                hits=tr.hits,
                error=tr.error,
                elapsed_sec=tr.elapsed_sec,
                log_path=tr.raw_log_path,
            ))

        # Dedup + cross-confirm
        deduped, cross_confirmed = dedup_and_confirm(all_hits)

        known_set = set(known_phones)
        return RunResult(
            target_name=target_name,
            mode="aggregate",
            modules_run=modules_run,
            outcomes=outcomes,
            all_hits=deduped,
            cross_confirmed=cross_confirmed,
            new_phones=sorted({h.value for h in deduped if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0}),
            new_emails=sorted({h.value for h in deduped if h.observable_type == "email" and h.confidence > 0}),
            errors=errors,
            started_at=started,
            finished_at=datetime.now().isoformat(),
        )
