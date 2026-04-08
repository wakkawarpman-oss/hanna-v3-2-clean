"""
worker.py — Isolated adapter execution for process-pool parallelism.

Provides _run_adapter_isolated() which runs a single adapter in its own
process (picklable contract), plus ReconTask / TaskResult data classes
used by the runners.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.base import AdapterExecutionError, ReconAdapter, ReconHit
from config import (
    ADAPTER_REQ_CAP,
    LOG_ENCRYPT,
    LOG_ENCRYPT_KEY,
    MODULE_WORKER_TIMEOUT,
    PRIORITY_WORKER_TIMEOUT,
    WORKER_TIMEOUT,
)
from registry import LANE_ORDER, MODULES, MODULE_LANE, MODULE_PRIORITY


@dataclass
class ReconTask:
    """Atomic unit of work for the worker pool."""
    module_name: str
    priority: int
    adapter_cls: type[ReconAdapter]
    target_name: str
    known_phones: list[str]
    known_usernames: list[str]
    lane: str
    proxy: str | None
    timeout: float
    worker_timeout: float
    leak_dir: str | None

    def __lt__(self, other: ReconTask) -> bool:
        return (LANE_ORDER.get(self.lane, 99), self.priority) < (
            LANE_ORDER.get(other.lane, 99), other.priority
        )


@dataclass
class TaskResult:
    """Result from a single adapter execution."""
    module_name: str
    lane: str
    hits: list[ReconHit]
    error: str | None
    error_kind: str | None
    elapsed_sec: float
    raw_log_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module_name,
            "hits": [h.to_dict() for h in self.hits],
            "error": self.error,
            "error_kind": self.error_kind,
            "elapsed": self.elapsed_sec,
            "log_path": self.raw_log_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], lane: str = "fast") -> TaskResult:
        return cls(
            module_name=str(payload.get("module", "")),
            lane=lane,
            hits=[ReconHit.from_dict(h) for h in payload.get("hits", [])],
            error=payload.get("error"),
            error_kind=payload.get("error_kind"),
            elapsed_sec=float(payload.get("elapsed", 0.0)),
            raw_log_path=str(payload.get("log_path", "")),
        )


def build_tasks(
    module_names: list[str],
    target_name: str,
    known_phones: list[str],
    known_usernames: list[str],
    proxy: str | None,
    timeout: float,
    leak_dir: str | None,
) -> tuple[list[ReconTask], list[dict]]:
    """Build a sorted task list from module names. Returns (tasks, errors)."""
    tasks: list[ReconTask] = []
    errors: list[dict] = []
    for mod_name in module_names:
        adapter_cls = MODULES.get(mod_name)
        if not adapter_cls:
            errors.append({"module": mod_name, "error": f"Unknown module: {mod_name}", "error_kind": "unknown_module"})
            continue
        tasks.append(ReconTask(
            module_name=mod_name,
            priority=MODULE_PRIORITY.get(mod_name, 3),
            adapter_cls=adapter_cls,
            target_name=target_name,
            known_phones=known_phones,
            known_usernames=known_usernames,
            lane=MODULE_LANE.get(mod_name, "fast"),
            proxy=proxy,
            timeout=timeout,
            worker_timeout=MODULE_WORKER_TIMEOUT.get(
                mod_name,
                PRIORITY_WORKER_TIMEOUT.get(MODULE_PRIORITY.get(mod_name, 3), WORKER_TIMEOUT),
            ),
            leak_dir=leak_dir,
        ))
    tasks.sort()
    return tasks, errors


def _run_adapter_isolated(
    adapter_cls_name: str,
    region: str,
    proxy: str | None,
    timeout: float,
    worker_timeout: float,
    leak_dir: str | None,
    target_name: str,
    known_phones: list[str],
    known_usernames: list[str],
    log_dir: str,
) -> dict:
    """
    Execute a single adapter in an isolated worker process.
    Returns a plain dict (must be picklable for ProcessPoolExecutor).
    """
    import json
    import math
    import traceback

    from adapters.base import ReconHit as _Hit
    from config import ADAPTER_REQ_CAP as _CAP
    from registry import MODULES as _MODS

    t0 = time.monotonic()
    mod_name = adapter_cls_name
    adapter_cls = _MODS.get(mod_name)
    if not adapter_cls:
        return {"module": mod_name, "hits": [], "error": f"Unknown module: {mod_name}", "error_kind": "unknown_module", "elapsed": 0.0, "log_path": ""}

    log_path = str(Path(log_dir) / f"task_{mod_name}_{datetime.now().strftime('%H%M%S')}.log")
    lines: list[str] = [f"[{mod_name}] START  region={region}  {datetime.now().isoformat()}\n"]

    try:
        timed_out = False

        def _alarm_handler(_sig, _frame):
            raise TimeoutError(f"worker_timeout_exceeded:{int(worker_timeout)}s")

        if worker_timeout > 0 and hasattr(signal, "setitimer"):
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.setitimer(signal.ITIMER_REAL, max(1.0, float(worker_timeout)))

        capped_timeout = min(timeout, _CAP)
        adapter = adapter_cls(proxy=proxy, timeout=capped_timeout, leak_dir=leak_dir)
        hits = adapter.search(target_name, known_phones, known_usernames)
        if worker_timeout > 0 and hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0.0)

        elapsed = time.monotonic() - t0
        for h in hits:
            lines.append(f"  HIT {h.observable_type}:{h.value}  conf={h.confidence:.2f}  src={h.source_detail}\n")
        lines.append(f"[{mod_name}] DONE   {len(hits)} hit(s)  {elapsed:.1f}s\n")
        result = TaskResult(
            module_name=mod_name,
            lane="fast",
            hits=hits,
            error=None,
            error_kind=None,
            elapsed_sec=elapsed,
            raw_log_path=log_path,
        ).to_dict()
    except AdapterExecutionError as exc:
        if worker_timeout > 0 and hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0.0)
        elapsed = time.monotonic() - t0
        lines.append(f"[{mod_name}] SKIP  {exc}\n")
        result = TaskResult(
            module_name=mod_name,
            lane="fast",
            hits=[],
            error=str(exc),
            error_kind=getattr(exc, "error_kind", "adapter_error"),
            elapsed_sec=elapsed,
            raw_log_path=log_path,
        ).to_dict()
    except Exception as exc:
        if worker_timeout > 0 and hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0.0)
        elapsed = time.monotonic() - t0
        lines.append(f"[{mod_name}] ERROR  {exc}\n")
        lines.append(traceback.format_exc())
        result = TaskResult(
            module_name=mod_name,
            lane="fast",
            hits=[],
            error=str(exc),
            error_kind="adapter_error",
            elapsed_sec=elapsed,
            raw_log_path=log_path,
        ).to_dict()

    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(lines)
        if LOG_ENCRYPT:
            try:
                from cryptography.fernet import Fernet

                if not LOG_ENCRYPT_KEY:
                    raise ValueError("HANNA_LOG_KEY is required when HANNA_LOG_ENCRYPT=1")
                f = Fernet(LOG_ENCRYPT_KEY.encode("utf-8"))
                encrypted = f.encrypt(payload.encode("utf-8"))
                Path(log_path).write_bytes(encrypted)
            except Exception:
                Path(log_path).write_text(payload, encoding="utf-8")
        else:
            Path(log_path).write_text(payload, encoding="utf-8")
    except OSError:
        pass

    return result


def kill_process_group(exc: subprocess.TimeoutExpired) -> None:
    """Kill the entire process group spawned by a timed-out subprocess."""
    from adapters.cli_common import kill_process_group as _kill

    _kill(exc)
