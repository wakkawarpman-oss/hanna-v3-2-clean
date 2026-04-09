"""
models.py — Unified result model consumed by every execution mode.

All runners (chain, aggregate, manual) produce a ``RunResult`` that
wraps adapter hits, errors, timing, and optional entity clusters into
a single serialisable envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from adapters.base import ReconHit, ReconModuleOutcome, ReconReport


@dataclass
class AdapterOutcome:
    """Result of running one adapter (success or error)."""
    module_name: str
    lane: str
    hits: list[ReconHit] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    elapsed_sec: float = 0.0
    log_path: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "lane": self.lane,
            "hits": [hit.to_dict() for hit in self.hits],
            "error": self.error,
            "error_kind": self.error_kind,
            "elapsed_sec": self.elapsed_sec,
            "log_path": self.log_path,
        }

    def to_error_dict(self) -> dict[str, Any] | None:
        if not self.error:
            return None
        payload: dict[str, Any] = {
            "module": self.module_name,
            "error": self.error,
        }
        if self.error_kind:
            payload["error_kind"] = self.error_kind
        return payload


@dataclass
class RunResult:
    """
    Unified envelope returned by every runner.

    Regardless of whether the caller used chain / aggregate / manual mode
    the output is always a RunResult.
    """
    target_name: str
    mode: str                                       # "chain" | "aggregate" | "manual"
    modules_run: list[str] = field(default_factory=list)
    outcomes: list[AdapterOutcome] = field(default_factory=list)
    all_hits: list[ReconHit] = field(default_factory=list)
    cross_confirmed: list[ReconHit] = field(default_factory=list)
    new_phones: list[str] = field(default_factory=list)
    new_emails: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        standalone_errors: list[dict[str, Any]] = []
        for raw_error in self.errors:
            normalized = self._normalize_error_entry(raw_error)
            if not normalized:
                continue

            module_name = str(normalized.get("module", "")).strip()
            message = str(normalized.get("error", "")).strip()
            error_kind = str(normalized.get("error_kind", "")).strip() or None
            if module_name:
                outcome = next((item for item in self.outcomes if item.module_name == module_name), None)
                if outcome is None:
                    self.outcomes.append(AdapterOutcome(
                        module_name=module_name,
                        lane="unknown",
                        error=message,
                        error_kind=error_kind,
                    ))
                    continue
                if not outcome.error:
                    outcome.error = message
                    outcome.error_kind = error_kind
                    continue
                if outcome.error == message and outcome.error_kind == error_kind:
                    continue

            standalone_errors.append(normalized)

        self.errors = self._collect_error_entries(standalone_errors)

    # -- convenience helpers --------------------------------------------------

    @staticmethod
    def _normalize_error_entry(raw_error: Any) -> dict[str, Any] | None:
        if isinstance(raw_error, dict):
            message = str(raw_error.get("error", "")).strip()
            if not message:
                return None
            payload: dict[str, Any] = {"error": message}
            module_name = str(raw_error.get("module", "")).strip()
            if module_name:
                payload["module"] = module_name
            error_kind = str(raw_error.get("error_kind", "")).strip()
            if error_kind:
                payload["error_kind"] = error_kind
            return payload
        if isinstance(raw_error, str) and raw_error.strip():
            return {"error": raw_error.strip()}
        return None

    def _collect_error_entries(self, standalone_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str | None]] = set()

        def _append(entry: dict[str, Any]) -> None:
            module_name = str(entry.get("module", "")).strip()
            message = str(entry.get("error", "")).strip()
            error_kind_raw = entry.get("error_kind")
            error_kind = str(error_kind_raw).strip() if error_kind_raw else None
            key = (module_name, message, error_kind)
            if not message or key in seen:
                return
            seen.add(key)
            payload: dict[str, Any] = {"error": message}
            if module_name:
                payload["module"] = module_name
            if error_kind:
                payload["error_kind"] = error_kind
            entries.append(payload)

        for outcome in self.outcomes:
            entry = outcome.to_error_dict()
            if entry:
                _append(entry)
        for entry in standalone_errors:
            _append(entry)
        return entries

    @property
    def total_hits(self) -> int:
        return len(self.all_hits)

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

    def runtime_summary(self) -> dict[str, Any]:
        queued_modules = [str(item) for item in self.extra.get("queued_modules", []) if str(item)]
        queued = len(queued_modules) if queued_modules else max(len(self.outcomes), len(self.modules_run))

        error_entries: set[tuple[str, str, str | None]] = set()
        for outcome in self.outcomes:
            if outcome.error:
                error_entries.add((outcome.module_name, outcome.error, outcome.error_kind))
        for err in self.errors:
            module_name = str(err.get("module", ""))
            message = str(err.get("error", ""))
            if message:
                kind = str(err.get("error_kind")) if err.get("error_kind") else None
                error_entries.add((module_name, message, kind))

        timeout_count = sum(1 for _module, _message, kind in error_entries if kind == "timeout")
        skipped_missing_credentials = sum(1 for _module, _message, kind in error_entries if kind == "missing_credentials")
        missing_binary_count = sum(1 for _module, _message, kind in error_entries if kind == "missing_binary")
        dependency_unavailable_count = sum(1 for _module, _message, kind in error_entries if kind == "dependency_unavailable")
        worker_crash_count = sum(1 for _module, _message, kind in error_entries if kind == "worker_crash")
        failed_count = max(
            len(error_entries)
            - timeout_count
            - skipped_missing_credentials
            - missing_binary_count
            - dependency_unavailable_count
            - worker_crash_count,
            0,
        )
        exports = self.extra.get("exports", {}) if isinstance(self.extra.get("exports", {}), dict) else {}

        return {
            "target_name": self.target_name,
            "mode": self.mode,
            "queued": queued,
            "completed": self.success_count,
            "failed": failed_count,
            "timed_out": timeout_count,
            "skipped_missing_credentials": skipped_missing_credentials,
            "missing_binary": missing_binary_count,
            "dependency_unavailable": dependency_unavailable_count,
            "worker_crash": worker_crash_count,
            "exports": sorted(exports.keys()),
            "report_mode": self.extra.get("report_mode"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "target_name": self.target_name,
            "mode": self.mode,
            "modules_run": self.modules_run,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "all_hits": [hit.to_dict() for hit in self.all_hits],
            "cross_confirmed": [hit.to_dict() for hit in self.cross_confirmed],
            "new_phones": self.new_phones,
            "new_emails": self.new_emails,
            "errors": self.errors,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "runtime_summary": self.runtime_summary(),
            "extra": self.extra,
        }

    def to_recon_report(self) -> ReconReport:
        """Down-cast to legacy ReconReport for backward compatibility."""
        return ReconReport(
            target_name=self.target_name,
            modules_run=self.modules_run,
            hits=self.all_hits,
            started_at=self.started_at,
            finished_at=self.finished_at,
            new_phones=self.new_phones,
            new_emails=self.new_emails,
            cross_confirmed=self.cross_confirmed,
            outcomes=[
                ReconModuleOutcome(
                    module_name=outcome.module_name,
                    lane=outcome.lane,
                    hits=outcome.hits,
                    error=outcome.error,
                    error_kind=outcome.error_kind,
                    elapsed_sec=outcome.elapsed_sec,
                    log_path=outcome.log_path,
                )
                for outcome in self.outcomes
            ],
            errors=self.errors,
        )

    def summary_lines(self) -> list[str]:
        """Human-readable summary."""
        lines = [
            f"=== {self.mode.upper()} Run: {self.target_name} ===",
            f"Modules: {', '.join(self.modules_run)}",
            f"Time: {self.started_at} → {self.finished_at}",
            f"Hits: {self.total_hits}  |  Cross-confirmed: {len(self.cross_confirmed)}",
            f"New phones: {len(self.new_phones)}  |  New emails: {len(self.new_emails)}",
            f"Adapters OK: {self.success_count}/{len(self.outcomes)}  |  Errors: {self.error_count}",
        ]
        runtime = self.runtime_summary()
        runtime_line = (
            f"Runtime: queued={runtime['queued']}  completed={runtime['completed']}  "
            f"failed={runtime['failed']}  timed_out={runtime['timed_out']}  "
            f"skipped_missing_credentials={runtime['skipped_missing_credentials']}  "
            f"missing_binary={runtime['missing_binary']}  dependency_unavailable={runtime['dependency_unavailable']}  "
            f"worker_crash={runtime['worker_crash']}"
        )
        lines.append(runtime_line)
        if runtime["exports"]:
            lines.append(f"Exports: {', '.join(runtime['exports'])}")
        if runtime["report_mode"]:
            lines.append(f"Report mode: {runtime['report_mode']}")
        if self.new_phones:
            lines.append("\nNew Phone Numbers:")
            for phone in self.new_phones:
                best = max(
                    (h for h in self.all_hits if h.value == phone),
                    key=lambda h: h.confidence,
                    default=None,
                )
                if best:
                    xc = " CROSS-CONFIRMED" if any(
                        h.fingerprint == best.fingerprint for h in self.cross_confirmed
                    ) else ""
                    lines.append(f"  {phone}  (conf={best.confidence:.0%}, via {best.source_detail}){xc}")
        if self.new_emails:
            lines.append("\nNew Emails:")
            for email in self.new_emails:
                best = max(
                    (h for h in self.all_hits if h.value == email),
                    key=lambda h: h.confidence,
                    default=None,
                )
                if best:
                    lines.append(f"  {email}  (conf={best.confidence:.0%}, via {best.source_detail})")
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for err in self.errors:
                kind = err.get("error_kind")
                suffix = f" ({kind})" if kind else ""
                lines.append(f"  [{err.get('module', '?')}] {err.get('error', '')}{suffix}")
        return lines
