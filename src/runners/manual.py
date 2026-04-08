"""
runners.manual — Interactive single-adapter execution.

Instantiates one adapter by name, runs it directly (no worker pool),
and returns a RunResult.  Designed for interactive / debugging use.

Usage:
    runner = ManualRunner(proxy="socks5h://127.0.0.1:9050")
    result = runner.run(
        module_name="ua_phone",
        target_name="Hanna Dosenko",
        known_phones=["+380507133698"],
    )
"""
from __future__ import annotations

import time
from datetime import datetime

from adapters.base import AdapterExecutionError, ReconHit
from models import AdapterOutcome, RunResult
from registry import MODULES, MODULE_LANE


class ManualRunner:
    """Run a single adapter interactively (no process isolation)."""

    def __init__(
        self,
        proxy: str | None = None,
        timeout: float = 15.0,
        leak_dir: str | None = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.leak_dir = leak_dir

    def run(
        self,
        module_name: str,
        target_name: str,
        known_phones: list[str] | None = None,
        known_usernames: list[str] | None = None,
    ) -> RunResult:
        known_phones = known_phones or []
        known_usernames = known_usernames or []

        adapter_cls = MODULES.get(module_name)
        if not adapter_cls:
            return RunResult(
                target_name=target_name,
                mode="manual",
                extra={"queued_modules": [module_name]},
                errors=[{"module": module_name, "error": f"Unknown module: {module_name}", "error_kind": "unknown_module"}],
                started_at=datetime.now().isoformat(),
                finished_at=datetime.now().isoformat(),
            )

        started = datetime.now().isoformat()
        lane = MODULE_LANE.get(module_name, "fast")

        print(f"  [{module_name}] Starting manual run ({adapter_cls.region.upper()})...")

        t0 = time.monotonic()
        try:
            adapter = adapter_cls(
                proxy=self.proxy, timeout=self.timeout, leak_dir=self.leak_dir,
            )
            hits = adapter.search(target_name, known_phones, known_usernames)
            elapsed = time.monotonic() - t0
            print(f"  [{module_name}] → {len(hits)} hit(s)  ({elapsed:.1f}s)")

            outcome = AdapterOutcome(
                module_name=module_name, lane=lane,
                hits=hits, error_kind=None, elapsed_sec=elapsed,
            )
            known_set = set(known_phones)
            return RunResult(
                target_name=target_name,
                mode="manual",
                modules_run=[module_name],
                outcomes=[outcome],
                all_hits=hits,
                new_phones=sorted({h.value for h in hits if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0}),
                new_emails=sorted({h.value for h in hits if h.observable_type == "email" and h.confidence > 0}),
                started_at=started,
                finished_at=datetime.now().isoformat(),
                extra={"queued_modules": [module_name]},
            )
        except AdapterExecutionError as exc:
            elapsed = time.monotonic() - t0
            print(f"  [{module_name}] SKIP: {exc}  ({elapsed:.1f}s)")
            return RunResult(
                target_name=target_name,
                mode="manual",
                modules_run=[module_name],
                outcomes=[AdapterOutcome(
                    module_name=module_name, lane=lane,
                    error=str(exc), error_kind=getattr(exc, "error_kind", "adapter_error"), elapsed_sec=elapsed,
                )],
                errors=[{"module": module_name, "error": str(exc), "error_kind": getattr(exc, "error_kind", "adapter_error")}],
                started_at=started,
                finished_at=datetime.now().isoformat(),
                extra={"queued_modules": [module_name]},
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  [{module_name}] ERROR: {exc}  ({elapsed:.1f}s)")
            return RunResult(
                target_name=target_name,
                mode="manual",
                modules_run=[module_name],
                outcomes=[AdapterOutcome(
                    module_name=module_name, lane=lane,
                    error=str(exc), error_kind="adapter_error", elapsed_sec=elapsed,
                )],
                errors=[{"module": module_name, "error": str(exc), "error_kind": "adapter_error"}],
                started_at=started,
                finished_at=datetime.now().isoformat(),
                extra={"queued_modules": [module_name]},
            )

    @staticmethod
    def list_modules() -> list[dict[str, str]]:
        """List available adapter modules with metadata."""
        rows = []
        for name, cls in sorted(MODULES.items()):
            rows.append({
                "name": name,
                "region": cls.region,
                "lane": MODULE_LANE.get(name, "?"),
                "doc": (cls.__doc__ or "").strip().split("\n")[0],
            })
        return rows
