#!/usr/bin/env python3
from __future__ import annotations

"""
run_discovery.py — Legacy DiscoveryEngine entrypoint.

Usage:
    python3 run_discovery.py [--exports-dir DIR] [--output HTML_PATH] [--db DB_PATH]

Deep recon mode:
    python3 run_discovery.py --target "Hanna Dosenko" --modules "ua_leak,ru_leak,vk_graph" --verify
    python3 run_discovery.py --target "Hanna Dosenko" --mode deep-all --verify

Preferred operator path:
    ./scripts/hanna list
    ./scripts/hanna chain --target "Hanna Dosenko" --modules full-spectrum
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DEFAULT_DB_PATH, RUNS_ROOT
from discovery_engine import DiscoveryEngine
from registry import MODULE_PRESETS, MODULES, MODULE_LANE

log = logging.getLogger("hanna.run_discovery")

LEGACY_WARNING = (
    "[legacy] run_discovery.py is kept for compatibility. "
    "Prefer './scripts/hanna' or 'python3 src/cli.py' for operator workflows."
)


def _parse_targets_file(path: str) -> list[dict[str, list[str] | str]]:
    """
    Parse batch targets file.

    Format per line:
      target|phone1,phone2|username1,username2

    Lines starting with '#' or empty lines are ignored.
    """
    items: list[dict[str, list[str] | str]] = []
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"targets file not found: {path}")

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 3:
            parts.append("")

        target = parts[0]
        if not target:
            continue

        phones = [p.strip() for p in parts[1].split(",") if p.strip()]
        usernames = [u.strip() for u in parts[2].split(",") if u.strip()]
        items.append({
            "target": target,
            "phones": phones,
            "usernames": usernames,
        })

    return items


def main():
    parser = argparse.ArgumentParser(
        description="Run recursive discovery engine on legacy OSINT exports",
        epilog="Legacy compatibility path. Prefer './scripts/hanna list|chain|aggregate|manual|preflight'.",
    )
    parser.add_argument("--exports-dir", default=str(RUNS_ROOT / "exports"))
    parser.add_argument("--output", default=None, help="Output HTML path")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--list-modules", action="store_true", help="List available adapters and presets, then exit")
    parser.add_argument("--confirmed-file", nargs="*", default=[], help="JSON manifest(s) with analyst-confirmed evidence to inject before entity resolution")

    # Deep recon options
    parser.add_argument("--target", default=None, help="Target name for deep recon (e.g. 'Hanna Dosenko')")
    parser.add_argument("--modules", default=None, help="Comma-separated recon modules (ua_leak,ru_leak,vk_graph,avito,ua_phone)")
    parser.add_argument("--mode", default=None, help="Module preset: deep-ua, deep-ru, deep-all, leaks_all")
    parser.add_argument("--targets-file", default=None, help="Batch target file: target|phone1,phone2|username1,username2")
    parser.add_argument("--verify", action="store_true", help="Run profile verification after discovery")
    parser.add_argument("--verify-all", action="store_true", help="Verify ALL unchecked profiles (no limit)")
    parser.add_argument("--verify-content", action="store_true", help="Content-verify soft_match URLs (full GET + name matching)")
    parser.add_argument("--leaks-dir", default=None, help="Directory with JSONL leak files (default: runs/leaks/)")
    parser.add_argument("--phone-resolve", action="store_true", help="Run live phone resolution for known numbers")
    parser.add_argument("--proxy", default=None, help="SOCKS5 proxy for deep recon (e.g. socks5h://127.0.0.1:9050)")
    parser.add_argument("--report-mode", choices=["internal", "shareable", "strict"], default="shareable", help="HTML dossier redaction level")
    parser.add_argument("--no-legacy-warning", action="store_true", help="Suppress compatibility warning for scripted legacy usage")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not args.no_legacy_warning:
        print(LEGACY_WARNING, file=sys.stderr)

    if args.list_modules:
        print("\n=== Available Adapters ===")
        print(f"{'Name':<18} {'Lane':<6} Description")
        print("-" * 70)
        for name, adapter_cls in sorted(MODULES.items()):
            doc = (adapter_cls.__doc__ or "").strip().splitlines()[0] if adapter_cls.__doc__ else ""
            print(f"{name:<18} {MODULE_LANE.get(name, 'fast'):<6} {doc[:40]}")

        print(f"\n=== Presets ({len(MODULE_PRESETS)}) ===")
        for name, mods in MODULE_PRESETS.items():
            print(f"  {name:<20} -> {', '.join(mods)}")
        return

    exports = Path(args.exports_dir)
    metas = sorted(exports.glob("*.json"))
    log.info("Found %d metadata files in %s", len(metas), exports)

    # Default output
    if not args.output:
        out_dir = exports / "html" / "dossiers"
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output = str(out_dir / "discovery_dossier.html")

    engine = DiscoveryEngine(db_path=args.db)

    # Ingest all
    results = {"ingested": 0, "rejected": 0, "skipped": 0}
    for meta_path in metas:
        result = engine.ingest_metadata(meta_path)
        status = result.get("status", "unknown")
        if status == "ingested":
            results["ingested"] += 1
        elif status == "rejected":
            results["rejected"] += 1
        else:
            results["skipped"] += 1

    confirmed_results = []
    for confirmed_path in args.confirmed_file:
        result = engine.ingest_confirmed_evidence(confirmed_path)
        confirmed_results.append(result)

    log.info("Ingestion: %d ingested, %d rejected, %d skipped",
             results['ingested'], results['rejected'], results['skipped'])
    if confirmed_results:
        log.info("Confirmed evidence imports:")
        for item in confirmed_results:
            log.info("  %s: %d imported, %d duplicate(s)",
                     item['label'], item['imported'], item['duplicates'])

    # Resolve entities
    clusters = engine.resolve_entities()
    log.info("Entity resolution: %d identity cluster(s)", len(clusters))
    for i, c in enumerate(clusters[:5]):
        obs_types = {}
        for obs in c.observables:
            obs_types[obs.obs_type] = obs_types.get(obs.obs_type, 0) + 1
        type_summary = ", ".join(f"{k}:{v}" for k, v in sorted(obs_types.items()))
        log.info("  Cluster %d: \"%s\" — %d obs (%s), %d URLs, conf=%.0f%%",
                 i+1, c.label, len(c.observables), type_summary, len(c.profile_urls), c.confidence * 100)

    # Show pivot opportunities
    queue = engine.get_pivot_queue()
    if queue:
        log.info("Auto-pivot queue: %d pending task(s)", len(queue))
        for item in queue[:10]:
            log.info("  [%s] %s → %s", item['obs_type'], item['value'], ', '.join(item['suggested_tools']))

    # ── Deep recon (Phase 5) ──
    deep_recon_result = None
    deep_recon_results: list[dict] = []
    modules = None
    if args.mode:
        modules = [args.mode]  # resolved as preset by DeepReconRunner
    elif args.modules:
        modules = [m.strip() for m in args.modules.split(",") if m.strip()]

    if args.targets_file:
        batch_targets = _parse_targets_file(args.targets_file)
        log.info("Batch deep recon targets: %d", len(batch_targets))
        for i, item in enumerate(batch_targets, start=1):
            target = str(item["target"])
            phones = list(item["phones"])
            usernames = list(item["usernames"])
            log.info("[%d/%d] Deep recon target: %s", i, len(batch_targets), target)
            if phones:
                log.info("  Seed phones: %s", phones)
            if usernames:
                log.info("  Seed usernames: %s", usernames)

            result, _report = engine.run_deep_recon(
                target_name=target,
                modules=modules,
                proxy=args.proxy,
                leak_dir=args.leaks_dir,
                known_phones_override=phones,
                known_usernames_override=usernames,
            )
            deep_recon_results.append(result)
            log.info("Deep recon result: %s", json.dumps(result, indent=2, default=str))

            if result.get("new_observables", 0) > 0:
                log.info("Re-resolving entities with new deep recon data...")
                clusters = engine.resolve_entities()
                log.info("Updated: %d identity cluster(s)", len(clusters))

        deep_recon_result = deep_recon_results[-1] if deep_recon_results else None
    elif args.target or args.modules or args.mode:
        deep_recon_result, _report = engine.run_deep_recon(
            target_name=args.target,
            modules=modules,
            proxy=args.proxy,
            leak_dir=args.leaks_dir,
        )
        deep_recon_results.append(deep_recon_result)
        log.info("Deep recon result: %s", json.dumps(deep_recon_result, indent=2, default=str))

        # Re-resolve entities with new data
        if deep_recon_result.get("new_observables", 0) > 0:
            log.info("Re-resolving entities with new deep recon data...")
            clusters = engine.resolve_entities()
            log.info("Updated: %d identity cluster(s)", len(clusters))

    # ── Phone resolve shortcut ──
    if args.phone_resolve and not deep_recon_result:
        deep_recon_result, _report = engine.run_deep_recon(
            target_name=args.target,
            modules=["ua_phone"],
            proxy=args.proxy,
            leak_dir=args.leaks_dir,
        )
        log.info("Phone resolve result: %s", json.dumps(deep_recon_result, indent=2, default=str))
        if deep_recon_result.get("new_observables", 0) > 0:
            clusters = engine.resolve_entities()
            log.info("Updated: %d cluster(s)", len(clusters))

    # ── Profile verification ──
    if args.verify or args.verify_all:
        max_checks = 999999 if args.verify_all else 200
        log.info("Running profile verification (max %d)...", max_checks)
        engine.verify_profiles(max_checks=max_checks, timeout=4.0, proxy=args.proxy)
        pstats = engine.get_profile_stats()
        log.info("Profile stats: %s", pstats)

    # ── Content verification (Phase 6A) ──
    if args.verify_content:
        log.info("Running content verification on soft_match URLs...")
        cv_result = engine.verify_content(max_checks=200, timeout=8.0, proxy=args.proxy)
        log.info("Content verify: %s", cv_result)
        pstats = engine.get_profile_stats()
        log.info("Profile stats after content verify: %s", pstats)

    # Stats
    stats = engine.get_stats()
    log.info("Stats: %s", json.dumps(stats, indent=2, default=str))

    # Render report
    engine.render_graph_report(output_path=args.output, redaction_mode=args.report_mode)
    log.info("Graph-centric dossier written to: %s", args.output)

    # Also create a latest symlink
    latest = Path(args.output).parent / "latest_discovery.html"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(Path(args.output).name)
    log.info("Latest link: %s", latest)


if __name__ == "__main__":
    main()
