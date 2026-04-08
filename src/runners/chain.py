"""
runners.chain — Sequential pipeline runner.

Executes the full discovery workflow in order:
  ingest → resolve → deep-recon → verify → render

Each stage feeds the next.  The DiscoveryEngine is the backing store;
the ChainRunner acts as a thin orchestration layer that delegates to it.

Usage:
    runner = ChainRunner(db_path="discovery.db", proxy="socks5h://127.0.0.1:9050")
    result = runner.run(
        exports_dir="runs/exports",
        target_name="Hanna Dosenko",
        modules=["ua_leak", "ru_leak"],
        verify=True,
    )
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from adapters.base import ReconHit
from config import DEFAULT_DB_PATH, RUNS_ROOT
from models import AdapterOutcome, RunResult
from registry import resolve_modules

log = logging.getLogger("hanna.runners.chain")


class ChainRunner:
    """Full discovery pipeline: ingest → resolve → recon → verify → render."""

    def __init__(
        self,
        db_path: str = str(DEFAULT_DB_PATH),
        proxy: str | None = None,
        leak_dir: str | None = None,
        max_workers: int = 4,
    ):
        self.db_path = db_path
        self.proxy = proxy
        self.leak_dir = leak_dir
        self.max_workers = max_workers

    def run(
        self,
        exports_dir: str | None = None,
        target_name: str | None = None,
        known_phones: list[str] | None = None,
        known_usernames: list[str] | None = None,
        modules: list[str] | None = None,
        verified_files: list[str] | None = None,
        verify: bool = False,
        verify_all: bool = False,
        verify_content: bool = False,
        output_path: str | None = None,
        report_mode: str = "shareable",
    ) -> RunResult:
        from discovery_engine import DiscoveryEngine

        started = datetime.now().isoformat()
        exports = Path(exports_dir) if exports_dir else RUNS_ROOT / "exports"

        if not output_path:
            out_dir = exports / "html" / "dossiers"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(out_dir / "discovery_dossier.html")

        engine = DiscoveryEngine(db_path=self.db_path)

        # ── Stage 1: Ingest ──
        metas = sorted(exports.glob("*.json"))
        ing = {"ingested": 0, "rejected": 0, "skipped": 0}
        for mp in metas:
            res = engine.ingest_metadata(mp)
            s = res.get("status", "unknown")
            if s == "ingested":
                ing["ingested"] += 1
            elif s == "rejected":
                ing["rejected"] += 1
            else:
                ing["skipped"] += 1
        log.info("Ingest: %d ok, %d rejected, %d skipped", ing["ingested"], ing["rejected"], ing["skipped"])

        for cf in (verified_files or []):
            engine.ingest_confirmed_evidence(cf)

        # ── Stage 2: Entity resolution ──
        clusters = engine.resolve_entities()
        log.info("Entity resolution: %d cluster(s)", len(clusters))

        # ── Stage 3: Deep recon ──
        module_names = resolve_modules(modules)
        recon_result: dict | None = None
        recon_report = None
        all_hits: list[ReconHit] = []
        errors: list[dict] = []
        outcomes: list[AdapterOutcome] = []

        if target_name or modules:
            recon_result, recon_report = engine.run_deep_recon(
                target_name=target_name,
                modules=module_names if modules else None,
                proxy=self.proxy,
                leak_dir=self.leak_dir,
                known_phones_override=known_phones,
                known_usernames_override=known_usernames,
            )
            if recon_result and recon_result.get("new_observables", 0) > 0:
                clusters = engine.resolve_entities()

            errors = recon_result.get("errors", []) if recon_result else []
            all_hits = list(recon_report.hits) if recon_report else []
            for mod in (recon_result or {}).get("modules_run", []):
                module_hits = [h for h in all_hits if h.source_module == mod]
                module_error = next((item for item in errors if item.get("module") == mod), None)
                outcomes.append(AdapterOutcome(
                    module_name=mod,
                    lane="chain",
                    hits=module_hits,
                    error=module_error.get("error") if module_error else None,
                    error_kind=module_error.get("error_kind") if module_error else None,
                ))

        # ── Stage 4: Verification ──
        if verify or verify_all:
            max_checks = 999_999 if verify_all else 200
            engine.verify_profiles(max_checks=max_checks, timeout=4.0, proxy=self.proxy)
        if verify_content:
            engine.verify_content(max_checks=200, timeout=8.0, proxy=self.proxy)

        # ── Stage 5: Render ──
        engine.render_graph_report(output_path=output_path, redaction_mode=report_mode)
        log.info("Dossier: %s", output_path)

        return RunResult(
            target_name=target_name or (clusters[0].label if clusters else "unknown"),
            mode="chain",
            modules_run=(recon_result or {}).get("modules_run", []),
            outcomes=outcomes,
            all_hits=all_hits,
            errors=errors,
            started_at=started,
            finished_at=datetime.now().isoformat(),
            new_phones=(recon_result or {}).get("new_phones", []),
            new_emails=(recon_result or {}).get("new_emails", []),
            extra={
                "queued_modules": module_names,
                "ingestion": ing,
                "clusters": len(clusters),
                "output_path": output_path,
                "report_mode": report_mode,
                "stats": engine.get_stats(),
            },
        )
