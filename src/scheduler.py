"""Shared lane scheduler for deep_recon and aggregate runners."""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field

from adapters.base import ReconHit
from config import CROSS_CONFIRM_BOOST
from worker import ReconTask, TaskResult, _run_adapter_isolated


@dataclass
class SchedulerResult:
    all_hits: list[ReconHit] = field(default_factory=list)
    modules_run: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    task_results: list[TaskResult] = field(default_factory=list)


class LaneScheduler:
    """Dispatch recon tasks by lane with worker isolation and timeout controls."""

    @staticmethod
    def dispatch(
        tasks: list[ReconTask],
        max_workers: int,
        log_dir: str,
        label: str = "",
        event_callback: Callable[[dict], None] | None = None,
    ) -> SchedulerResult:
        result = SchedulerResult()
        n_workers = min(max_workers, len(tasks)) or 1
        prefix = f"[{label}] " if label else ""
        print(f"  {prefix}Dispatching {len(tasks)} task(s) across {n_workers} worker(s)  [Fast Lane -> Slow Lane | P0->P3]")
        LaneScheduler._emit(
            event_callback,
            {
                "type": "dispatch_started",
                "label": label,
                "task_count": len(tasks),
                "workers": n_workers,
            },
        )

        for lane_name in ("fast", "slow"):
            lane_tasks = [t for t in tasks if t.lane == lane_name]
            if not lane_tasks:
                continue

            lane_workers = min(max_workers, len(lane_tasks)) or 1
            print(f"\n  {prefix}{lane_name.upper()} LANE  |  {len(lane_tasks)} task(s) across {lane_workers} worker(s)")
            LaneScheduler._emit(
                event_callback,
                {
                    "type": "lane_started",
                    "label": label,
                    "lane": lane_name,
                    "task_count": len(lane_tasks),
                    "workers": lane_workers,
                },
            )

            pool = ProcessPoolExecutor(max_workers=lane_workers)
            future_map: dict[Future, ReconTask] = {}
            submitted_at: dict[Future, float] = {}

            for task in lane_tasks:
                plabel = f"P{task.priority}"
                print(f"  [{task.module_name}] Queued  ({plabel}, {task.adapter_cls.region.upper()} segment)")
                LaneScheduler._emit(
                    event_callback,
                    {
                        "type": "task_queued",
                        "label": label,
                        "lane": lane_name,
                        "module": task.module_name,
                        "priority": task.priority,
                        "region": task.adapter_cls.region,
                    },
                )
                fut = pool.submit(
                    _run_adapter_isolated,
                    adapter_cls_name=task.module_name,
                    region=task.adapter_cls.region,
                    proxy=task.proxy,
                    timeout=task.timeout,
                    worker_timeout=task.worker_timeout,
                    leak_dir=task.leak_dir,
                    target_name=task.target_name,
                    known_phones=task.known_phones,
                    known_usernames=task.known_usernames,
                    log_dir=log_dir,
                )
                future_map[fut] = task
                submitted_at[fut] = time.monotonic()

            pending = set(future_map)
            try:
                while pending:
                    done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)

                    for fut in done:
                        task = future_map[fut]
                        try:
                            result_dict = fut.result(timeout=10)
                        except Exception as exc:
                            msg = f"worker_crash: {exc}"
                            result.errors.append({"module": task.module_name, "error": msg, "error_kind": "worker_crash"})
                            result.task_results.append(TaskResult(
                                module_name=task.module_name,
                                lane=task.lane,
                                hits=[],
                                error=msg,
                                error_kind="worker_crash",
                                elapsed_sec=0.0,
                                raw_log_path="",
                            ))
                            print(f"  [{task.module_name}] CRASHED: {exc}")
                            LaneScheduler._emit(
                                event_callback,
                                {
                                    "type": "task_crashed",
                                    "label": label,
                                    "lane": task.lane,
                                    "module": task.module_name,
                                    "error": msg,
                                },
                            )
                            continue

                        tr = TaskResult.from_dict(result_dict, lane=task.lane)
                        result.task_results.append(tr)
                        result.modules_run.append(tr.module_name)
                        if tr.error:
                            result.errors.append({"module": tr.module_name, "error": tr.error, "error_kind": tr.error_kind})
                            print(f"  [{tr.module_name}] ERROR: {tr.error}  ({tr.elapsed_sec:.1f}s)")
                            LaneScheduler._emit(
                                event_callback,
                                {
                                    "type": "task_error",
                                    "label": label,
                                    "lane": tr.lane,
                                    "module": tr.module_name,
                                    "error": tr.error,
                                    "elapsed_sec": tr.elapsed_sec,
                                    "hit_count": 0,
                                },
                            )
                        else:
                            result.all_hits.extend(tr.hits)
                            print(f"  [{tr.module_name}] -> {len(tr.hits)} hit(s)  ({tr.elapsed_sec:.1f}s)")
                            LaneScheduler._emit(
                                event_callback,
                                {
                                    "type": "task_done",
                                    "label": label,
                                    "lane": tr.lane,
                                    "module": tr.module_name,
                                    "elapsed_sec": tr.elapsed_sec,
                                    "hit_count": len(tr.hits),
                                },
                            )

                    now = time.monotonic()
                    timed_out = [
                        f for f in pending
                        if now - submitted_at[f] >= future_map[f].worker_timeout
                    ]
                    for fut in timed_out:
                        pending.discard(fut)
                        task = future_map[fut]
                        fut.cancel()
                        msg = f"TIMEOUT ({int(task.worker_timeout)}s)"
                        result.errors.append({"module": task.module_name, "error": msg, "error_kind": "timeout"})
                        result.task_results.append(TaskResult(
                            module_name=task.module_name,
                            lane=task.lane,
                            hits=[],
                            error=msg,
                            error_kind="timeout",
                            elapsed_sec=float(task.worker_timeout),
                            raw_log_path="",
                        ))
                        print(f"  [{task.module_name}] {msg} - cancelled")
                        LaneScheduler._emit(
                            event_callback,
                            {
                                "type": "task_timeout",
                                "label": label,
                                "lane": task.lane,
                                "module": task.module_name,
                                "error": msg,
                                "elapsed_sec": float(task.worker_timeout),
                            },
                        )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            lane_ok = sum(1 for tr in result.task_results if tr.lane == lane_name and not tr.error)
            print(f"  {prefix}{lane_name.upper()} LANE complete  |  {lane_ok}/{len(lane_tasks)} task(s) finished cleanly")
            LaneScheduler._emit(
                event_callback,
                {
                    "type": "lane_complete",
                    "label": label,
                    "lane": lane_name,
                    "ok_count": lane_ok,
                    "task_count": len(lane_tasks),
                },
            )

        LaneScheduler._emit(
            event_callback,
            {
                "type": "dispatch_complete",
                "label": label,
                "modules_run": list(result.modules_run),
                "errors": len(result.errors),
                "hits": len(result.all_hits),
            },
        )
        return result

    @staticmethod
    def _emit(event_callback: Callable[[dict], None] | None, payload: dict) -> None:
        if event_callback:
            event_callback(payload)


def dedup_and_confirm(all_hits: list[ReconHit]) -> tuple[list[ReconHit], list[ReconHit]]:
    """Deduplicate hits by fingerprint and tag cross-confirmed ones."""
    seen: dict[str, ReconHit] = {}
    for hit in all_hits:
        fp = hit.fingerprint
        if fp in seen:
            existing = seen[fp]
            if hit.confidence > existing.confidence:
                existing.confidence = hit.confidence
                existing.source_detail = hit.source_detail
            existing.cross_refs = list(set(existing.cross_refs + hit.cross_refs))
        else:
            seen[fp] = hit

    deduped = list(seen.values())

    source_counts: dict[str, set[str]] = {}
    for hit in all_hits:
        source_counts.setdefault(hit.fingerprint, set()).add(hit.source_module)

    cross_confirmed = [
        h for h in deduped
        if len(source_counts.get(h.fingerprint, set())) >= 2
    ]
    for hit in cross_confirmed:
        hit.confidence = min(1.0, hit.confidence + CROSS_CONFIRM_BOOST)

    return deduped, cross_confirmed
