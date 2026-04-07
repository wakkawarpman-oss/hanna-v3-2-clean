"""
deep_recon.py — UA + RU Deep Reconnaissance Runner (refactored)
================================================================

Thin orchestration layer.  Adapter implementations live in ``adapters/``,
module registry in ``registry.py``, worker isolation in ``worker.py``.

This file keeps DeepReconRunner and backward-compatible re-exports so
existing callers (discovery_engine.py, run_discovery.py) keep working.

Usage:
    from deep_recon import DeepReconRunner, ReconReport
    runner = DeepReconRunner(proxy="socks5h://127.0.0.1:9050")
    report = runner.run(
        target_name="Hanna Dosenko",
        known_phones=["+380507133698"],
        known_usernames=["hannadosenko"],
        modules=["ua_leak", "ru_leak", "vk_graph"],
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from adapters.base import ReconAdapter, ReconHit, ReconReport  # re-exported
from config import CROSS_CONFIRM_BOOST, RUNS_ROOT
from registry import (
    MODULE_LANE,
    MODULE_PRESETS,
    MODULE_PRIORITY,
    MODULES,
    resolve_modules,
)
from translit import transliterate_to_cyrillic as _transliterate_to_cyrillic  # noqa: F401 — backward compat
from scheduler import LaneScheduler, dedup_and_confirm
from worker import (
    build_tasks,
)

log = logging.getLogger("hanna.recon")


# ── Runner ───────────────────────────────────────────────────────

class DeepReconRunner:
    """
    Event-Driven OSINT orchestrator with priority-based worker pool.

    Architecture (v3.1 — refactored):
      - Adapters live in ``adapters/`` package (isolated modules).
      - Registry + presets in ``registry.py``.
      - Process-isolated worker in ``worker.py``.
      - This class only handles scheduling, dedup, and reporting.
    """

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
    ) -> ReconReport:
        """Run deep recon with priority-based parallel workers."""
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

        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        scheduled = LaneScheduler.dispatch(tasks=tasks, max_workers=self.max_workers, log_dir=self.log_dir, label="deep_recon")
        errors.extend(scheduled.errors)
        modules_run = scheduled.modules_run
        all_hits = scheduled.all_hits

        # ── Dedup + cross-confirm ──
        deduped, cross_confirmed = dedup_and_confirm(all_hits)

        known_set = set(known_phones)
        new_phones = sorted({h.value for h in deduped if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0})
        new_emails = sorted({h.value for h in deduped if h.observable_type == "email" and h.confidence > 0})

        report = ReconReport(
            target_name=target_name,
            modules_run=modules_run,
            hits=deduped,
            errors=errors,
            started_at=started,
            finished_at=datetime.now().isoformat(),
            new_phones=new_phones,
            new_emails=new_emails,
            cross_confirmed=cross_confirmed,
        )
        self._save_report(report)
        return report

    def _save_report(self, report: ReconReport) -> str | None:
        """Persist deep recon report as an atomic JSON artifact."""
        try:
            runs_dir = Path(self.log_dir).resolve().parent
            runs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = runs_dir / f"deep_recon_{stamp}.json"
            tmp_path = runs_dir / f".{out_path.name}.tmp"

            payload = {
                "target": report.target_name,
                "modules": report.modules_run,
                "hits": [h.to_dict() for h in report.hits],
                "errors": report.errors,
                "started": report.started_at,
                "finished": report.finished_at,
                "new_phones": report.new_phones,
                "new_emails": report.new_emails,
                "cross_confirmed": [h.to_dict() for h in report.cross_confirmed],
            }
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(out_path)
            return str(out_path)
        except OSError:
            return None

    @staticmethod
    def report_summary(report: ReconReport) -> str:
        """Human-readable summary of deep recon results."""
        infra_hits = [h for h in report.hits if h.observable_type == "infrastructure"]
        url_hits = [h for h in report.hits if h.observable_type == "url"]
        coord_hits = [h for h in report.hits if h.observable_type == "coordinates"]
        loc_hits = [h for h in report.hits if h.observable_type == "location"]

        lines = [
            f"=== Deep Recon Report: {report.target_name} ===",
            f"Modules run: {', '.join(report.modules_run)}",
            f"Time: {report.started_at} → {report.finished_at}",
            f"Total hits: {len(report.hits)}",
            f"New phones: {len(report.new_phones)}",
            f"New emails: {len(report.new_emails)}",
            f"Infrastructure: {len(infra_hits)}",
            f"URLs discovered: {len(url_hits)}",
            f"Coordinates: {len(coord_hits)}",
            f"Locations: {len(loc_hits)}",
            f"Cross-confirmed: {len(report.cross_confirmed)}",
        ]

        if report.new_phones:
            lines.append("\nNew Phone Numbers Found:")
            for phone in report.new_phones:
                best = max((h for h in report.hits if h.value == phone), key=lambda h: h.confidence)
                xconf = " CROSS-CONFIRMED" if any(h.fingerprint == best.fingerprint for h in report.cross_confirmed) else ""
                lines.append(f"  {phone}  (conf={best.confidence:.0%}, via {best.source_detail}){xconf}")

        if report.new_emails:
            lines.append("\nNew Emails Found:")
            for email in report.new_emails:
                best = max((h for h in report.hits if h.value == email), key=lambda h: h.confidence)
                lines.append(f"  {email}  (conf={best.confidence:.0%}, via {best.source_detail})")

        if infra_hits:
            lines.append("\nInfrastructure:")
            for h in sorted(infra_hits, key=lambda x: -x.confidence)[:15]:
                lines.append(f"  {h.value}  (conf={h.confidence:.0%}, via {h.source_detail})")

        if coord_hits:
            lines.append("\nGEOINT Coordinates:")
            for h in coord_hits:
                lines.append(f"  {h.value}  (from {h.source_detail})")

        if loc_hits:
            lines.append("\nLocations Resolved:")
            for h in loc_hits:
                lines.append(f"  {h.value[:80]}  (via {h.source_detail})")

        if url_hits:
            lines.append(f"\nURLs Found: {len(url_hits)} (top 10):")
            for h in sorted(url_hits, key=lambda x: -x.confidence)[:10]:
                lines.append(f"  {h.value}  (conf={h.confidence:.0%}, via {h.source_detail})")

        if report.errors:
            lines.append(f"\nErrors: {len(report.errors)}")
            for err in report.errors:
                lines.append(f"  [{err['module']}] {err['error']}")

        return "\n".join(lines)


# ── CLI (preserved for backward compat, delegates to cli.py) ──

def _cli():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="deep_recon",
        description="HANNA Deep Recon — UA/RU OSINT multi-adapter runner",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--module", metavar="NAME")
    group.add_argument("--mode", metavar="PRESET")
    group.add_argument("--list-modules", action="store_true")
    parser.add_argument("--target", metavar="NAME")
    parser.add_argument("--phones", nargs="*", default=[])
    parser.add_argument("--usernames", nargs="*", default=[])
    parser.add_argument("--proxy", metavar="URL")
    parser.add_argument("--leak-dir", metavar="PATH")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output-dir", metavar="DIR")
    args = parser.parse_args()

    if args.list_modules:
        print("Available modules:")
        for name, cls in MODULES.items():
            doc = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else ""
            print(f"  {name:20s}  [{cls.region.upper():6s}]  {doc}")
        print("\nPresets:")
        for preset, mods in MODULE_PRESETS.items():
            print(f"  {preset:20s}  → {', '.join(mods)}")
        return

    if not args.target:
        parser.error("--target required (use --list-modules to browse)")

    if args.module:
        mods = [args.module]
    elif args.mode:
        mods = resolve_modules([args.mode])
    else:
        mods = resolve_modules(["full-spectrum"])

    runner = DeepReconRunner(proxy=args.proxy, timeout=args.timeout, leak_dir=args.leak_dir)

    print(f"\n{'='*60}")
    print(f"  HANNA Deep Recon — {args.target}")
    print(f"  Modules: {', '.join(mods)}")
    print(f"{'='*60}\n")

    report = runner.run(
        target_name=args.target,
        known_phones=args.phones,
        known_usernames=args.usernames,
        modules=mods,
    )

    print(f"\n{DeepReconRunner.report_summary(report)}")

    out_dir = Path(args.output_dir) if args.output_dir else RUNS_ROOT
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rp = out_dir / f"deep_recon_{ts}.json"
    rp.write_text(json.dumps({
        "target": report.target_name,
        "modules": report.modules_run,
        "started": report.started_at,
        "finished": report.finished_at,
        "total_hits": len(report.hits),
        "new_phones": report.new_phones,
        "new_emails": report.new_emails,
        "cross_confirmed": len(report.cross_confirmed),
        "hits": [
            {"type": h.observable_type, "value": h.value, "source": h.source_module,
             "detail": h.source_detail, "confidence": h.confidence, "cross_refs": h.cross_refs}
            for h in report.hits
        ],
        "errors": report.errors,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved: {rp}")


if __name__ == "__main__":
    _cli()
