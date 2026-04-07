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

from adapters.base import ReconHit, ReconReport


@dataclass
class AdapterOutcome:
    """Result of running one adapter (success or error)."""
    module_name: str
    lane: str
    hits: list[ReconHit] = field(default_factory=list)
    error: str | None = None
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
            "elapsed_sec": self.elapsed_sec,
            "log_path": self.log_path,
        }


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

    # -- convenience helpers --------------------------------------------------

    @property
    def total_hits(self) -> int:
        return len(self.all_hits)

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

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
            "extra": self.extra,
        }

    def to_recon_report(self) -> ReconReport:
        """Down-cast to legacy ReconReport for backward compatibility."""
        return ReconReport(
            target_name=self.target_name,
            modules_run=self.modules_run,
            hits=self.all_hits,
            errors=self.errors,
            started_at=self.started_at,
            finished_at=self.finished_at,
            new_phones=self.new_phones,
            new_emails=self.new_emails,
            cross_confirmed=self.cross_confirmed,
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
                lines.append(f"  [{err.get('module', '?')}] {err.get('error', '')}")
        return lines
