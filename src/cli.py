#!/usr/bin/env python3
"""
cli.py — Unified terminal UI dispatcher for HANNA OSINT pipeline.

Three execution modes:
  chain      Full pipeline: ingest → resolve → deep-recon → verify → render
  aggregate  Parallel one-shot across selected adapters
  manual     Run a single adapter interactively
    tui        Launch operator cockpit scaffold

Usage:
    python3 cli.py chain   --target "Example Target" --modules ua_leak,ru_leak --verify
    python3 cli.py aggregate --target "example.com" --modules deep-all
    python3 cli.py manual  --module ua_phone --target "Phone Pivot" --phones "+380507133698"
    python3 cli.py list                              # list available adapters
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import DEFAULT_DB_PATH, RUNS_ROOT
from exporters import export_run_metadata_json, export_run_result_json, export_run_result_stix, export_run_result_zip
from preflight import format_preflight_report, has_hard_failures, preflight_summary, run_preflight
from registry import MODULE_PRESETS, MODULES, resolve_modules
from runtime_ops import reset_workspace
from smart_summary import summarize_payload

log = logging.getLogger("hanna.cli")


def _command_overview() -> str:
        return textwrap.dedent(
                """\
                Command overview:
                    chain (ch)       Full pipeline: ingest -> resolve -> recon -> verify -> render
                    aggregate (agg)  Parallel one-shot across selected adapters
                    manual (man)     Run one adapter directly
                    tui (ui)         Launch operator cockpit
                    list (ls)        Show adapters and presets
                    preflight (pf)   Check binaries, env vars, and runtime prerequisites
                    reset (rs)       Remove generated runtime state
                    summarize (sum)  Build a smart summary from raw text or file input

                Examples:
                    hanna chain --target "Example Target" --modules full-spectrum
                    hanna aggregate --target example.com --modules pd-infra-quick
                    hanna manual --module ua_phone --target "Phone Pivot" --phones "+380507133698"
                    hanna ui --plain
                    hanna preflight --modules full-spectrum --strict
                    hanna reset --confirm
                """
        )


def _parse_export_formats(value: str | None) -> list[str]:
    if not value:
        return []
    allowed = {"json", "metadata", "stix", "zip"}
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [item for item in formats if item not in allowed]
    if invalid:
        raise ValueError(f"Unsupported export format(s): {', '.join(invalid)}")
    return list(dict.fromkeys(formats))


def _build_run_metadata(result, exported: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_name": result.target_name,
        "mode": result.mode,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "modules_run": list(result.modules_run),
        "queued_modules": list(result.extra.get("queued_modules", [])) if isinstance(result.extra, dict) else [],
        "runtime_summary": result.runtime_summary(),
        "outcomes": [
            {
                "module_name": outcome.module_name,
                "lane": outcome.lane,
                "ok": outcome.ok,
                "hit_count": len(outcome.hits),
                "error": outcome.error,
                "error_kind": outcome.error_kind,
                "elapsed_sec": outcome.elapsed_sec,
                "log_path": outcome.log_path,
            }
            for outcome in result.outcomes
        ],
        "errors": list(result.errors),
        "artifacts": {
            "exports": exported,
            "output_path": result.extra.get("output_path") if isinstance(result.extra, dict) else None,
            "report_mode": result.extra.get("report_mode") if isinstance(result.extra, dict) else None,
        },
        "extra": result.extra,
    }


def _resolve_export_formats(export_formats_value: str | None, metadata_file: str | None) -> list[str]:
    export_formats = _parse_export_formats(export_formats_value)
    if metadata_file and "metadata" not in export_formats:
        export_formats.append("metadata")
    return export_formats


def _list_payload() -> dict[str, object]:
    from runners.manual import ManualRunner

    return {
        "modules": ManualRunner.list_modules(),
        "presets": [
            {"name": name, "modules": list(mods)}
            for name, mods in MODULE_PRESETS.items()
        ],
    }


def _export_result_artifacts(
    result,
    export_formats: list[str],
    export_dir: str | None,
    metadata_file: str | None = None,
    html_path: str | None = None,
    report_mode: str | None = None,
) -> dict[str, str]:
    if not export_formats:
        return {}
    target_dir = Path(export_dir) if export_dir else (RUNS_ROOT / "exports" / "artifacts")
    target_dir.mkdir(parents=True, exist_ok=True)
    exported: dict[str, str] = {}
    if "json" in export_formats:
        exported["json"] = str(export_run_result_json(result, target_dir))
    if "stix" in export_formats:
        exported["stix"] = str(export_run_result_stix(result, target_dir))
    if "zip" in export_formats:
        exported["zip"] = str(
            export_run_result_zip(
                result,
                target_dir,
                html_path=html_path,
                report_mode=report_mode,
            )
        )
    result_extra = getattr(result, "extra", None)
    if isinstance(result_extra, dict):
        result_extra["exports"] = exported
    if "metadata" in export_formats:
        metadata_path = export_run_metadata_json(
            _build_run_metadata(result, dict(exported)),
            target_dir,
            target_name=result.target_name,
            mode=result.mode,
            timestamp=result.finished_at or result.started_at,
            output_path=metadata_file,
        )
        exported["metadata"] = str(metadata_path)
        if isinstance(result_extra, dict):
            result_extra["exports"] = exported
    return exported


def _print_runtime_summary_block(result) -> None:
    print("Runtime summary JSON:")
    print(json.dumps(result.runtime_summary(), ensure_ascii=False, separators=(",", ":")))


def _print_runtime_summary_json_only(result) -> None:
    print(json.dumps(result.runtime_summary(), ensure_ascii=False, separators=(",", ":")))


def _json_only_enabled(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json_summary_only", False) or getattr(args, "json_only", False))


def _emit_json_payload(payload: dict[str, object], output_file: str | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if output_file:
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n", encoding="utf-8")
        return
    print(body)


def _add_runtime_output_flags(parser: argparse.ArgumentParser, *, runtime_json_default: bool) -> None:
    parser.add_argument(
        "--json-summary",
        action="store_true",
        default=runtime_json_default,
        help="Print compact runtime summary JSON block.",
    )
    parser.add_argument(
        "--json-summary-only",
        action="store_true",
        help="Print only compact runtime summary JSON for automation.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Alias for --json-summary-only.",
    )


def _run_with_optional_stdout_capture(callback, json_summary_only: bool):
    if not json_summary_only:
        return callback()
    with contextlib.redirect_stdout(io.StringIO()):
        return callback()


def _emit_run_output(result, exported: dict[str, str], *, print_runtime_json: bool, json_summary_only: bool) -> None:
    if json_summary_only:
        _print_runtime_summary_json_only(result)
        return
    for line in result.summary_lines():
        print(line)
    if print_runtime_json:
        _print_runtime_summary_block(result)
    for fmt, path in exported.items():
        print(f"Exported {fmt}: {path}")


def _build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="hanna",
        description="HANNA OSINT — modular reconnaissance dispatcher",
        epilog=_command_overview(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = root.add_subparsers(dest="mode", help="Execution mode")

    # ── chain ────────────────────────────────────────────────────
    ch = sub.add_parser("chain", aliases=["ch"], help="Full pipeline: ingest → resolve → recon → verify → render")
    ch.add_argument("--exports-dir", default=str(RUNS_ROOT / "exports"))
    ch.add_argument("--output", default=None, help="Output HTML path")
    ch.add_argument("--db", default=str(DEFAULT_DB_PATH))
    ch.add_argument("--target", default=None)
    ch.add_argument("--modules", default=None, help="Comma-separated modules or preset name")
    ch.add_argument("--phones", default=None, help="Comma-separated known phones")
    ch.add_argument("--usernames", default=None, help="Comma-separated known usernames")
    ch.add_argument("--confirmed-file", nargs="*", default=[])
    ch.add_argument("--verify", action="store_true")
    ch.add_argument("--verify-all", action="store_true")
    ch.add_argument("--verify-content", action="store_true")
    ch.add_argument("--proxy", default=None)
    ch.add_argument("--leak-dir", default=None)
    ch.add_argument("--no-preflight", action="store_true", help="Skip dependency preflight before running")
    ch.add_argument("--nuclei-profile", choices=["quick", "deep"], default=None)
    ch.add_argument("--report-mode", choices=["internal", "shareable", "strict"], default="shareable", help="HTML dossier redaction level")
    ch.add_argument("--export-formats", default=None, help="Comma-separated export formats: json,metadata,stix,zip")
    ch.add_argument("--export-dir", default=None, help="Directory for machine-readable exports")
    ch.add_argument("--metadata-file", default=None, help="Explicit output path for full metadata JSON export")
    _add_runtime_output_flags(ch, runtime_json_default=True)

    # ── aggregate ────────────────────────────────────────────────
    ag = sub.add_parser("aggregate", aliases=["agg"], help="Parallel one-shot across selected adapters")
    ag.add_argument("--target", required=True)
    ag.add_argument("--modules", default=None, help="Comma-separated modules or preset name")
    ag.add_argument("--phones", default=None)
    ag.add_argument("--usernames", default=None)
    ag.add_argument("--proxy", default=None)
    ag.add_argument("--leak-dir", default=None)
    ag.add_argument("--workers", type=int, default=4)
    ag.add_argument("--no-preflight", action="store_true", help="Skip dependency preflight before running")
    ag.add_argument("--nuclei-profile", choices=["quick", "deep"], default=None)
    ag.add_argument("--export-formats", default=None, help="Comma-separated export formats: json,metadata,stix,zip")
    ag.add_argument("--export-dir", default=None, help="Directory for machine-readable exports")
    ag.add_argument("--metadata-file", default=None, help="Explicit output path for full metadata JSON export")
    _add_runtime_output_flags(ag, runtime_json_default=True)

    # ── manual ───────────────────────────────────────────────────
    mn = sub.add_parser("manual", aliases=["man"], help="Run a single adapter interactively")
    mn.add_argument("--module", required=True, help="Adapter module name")
    mn.add_argument("--target", required=True)
    mn.add_argument("--phones", default=None)
    mn.add_argument("--usernames", default=None)
    mn.add_argument("--proxy", default=None)
    mn.add_argument("--leak-dir", default=None)
    mn.add_argument("--nuclei-profile", choices=["quick", "deep"], default=None)
    mn.add_argument("--export-formats", default=None, help="Comma-separated export formats: json,metadata,stix,zip")
    mn.add_argument("--export-dir", default=None, help="Directory for machine-readable exports")
    mn.add_argument("--metadata-file", default=None, help="Explicit output path for full metadata JSON export")
    _add_runtime_output_flags(mn, runtime_json_default=False)

    tui = sub.add_parser("tui", aliases=["ui"], help="Launch the HANNA operator cockpit scaffold")
    tui.add_argument("--target", default=None, help="Optional target label to preload into the cockpit")
    tui.add_argument("--modules", default=None, help="Comma-separated modules or preset name for cockpit context")
    tui.add_argument("--run-mode", choices=["idle", "manual", "aggregate", "chain"], default="idle")
    tui.add_argument("--module", default=None, help="Manual-mode adapter name")
    tui.add_argument("--phones", default=None, help="Comma-separated known phones")
    tui.add_argument("--usernames", default=None, help="Comma-separated known usernames")
    tui.add_argument("--workers", type=int, default=4)
    tui.add_argument("--db", default=str(DEFAULT_DB_PATH))
    tui.add_argument("--exports-dir", default=str(RUNS_ROOT / "exports"))
    tui.add_argument("--output", default=None, help="Optional HTML dossier path for chain mode")
    tui.add_argument("--verify", action="store_true")
    tui.add_argument("--verify-all", action="store_true")
    tui.add_argument("--verify-content", action="store_true")
    tui.add_argument("--proxy", default=None)
    tui.add_argument("--leak-dir", default=None)
    tui.add_argument("--no-preflight", action="store_true")
    tui.add_argument("--export-formats", default="json,metadata,stix,zip", help="Comma-separated export formats: json,metadata,stix,zip")
    tui.add_argument("--export-dir", default=None, help="Directory for machine-readable exports")
    tui.add_argument("--report-mode", choices=["internal", "shareable", "strict"], default="shareable")
    tui.add_argument("--plain", action="store_true", help="Use the safest TUI launch mode for VS Code and other low-capability terminals")

    # ── list ─────────────────────────────────────────────────────
    ls = sub.add_parser("list", aliases=["ls"], help="List available adapters and presets")
    ls.add_argument("--json-summary-only", action="store_true", help="Print only JSON module and preset inventory for automation.")
    ls.add_argument("--json-only", action="store_true", help="Alias for --json-summary-only.")
    ls.add_argument("--output-file", default=None, help="Write JSON output to a file instead of stdout.")

    # ── preflight ────────────────────────────────────────────────
    pf = sub.add_parser("preflight", aliases=["pf"], help="Check tool binaries, env vars, and runtime prerequisites")
    pf.add_argument("--strict", action="store_true", help="Exit non-zero when any hard failure is detected")
    pf.add_argument("--modules", default=None, help="Comma-separated modules or preset name to scope checks")
    pf.add_argument("--json-summary-only", action="store_true", help="Print only JSON preflight summary for automation.")
    pf.add_argument("--json-only", action="store_true", help="Alias for --json-summary-only.")

    rs = sub.add_parser("reset", aliases=["rs"], help="Remove generated runtime state such as DB, logs, and generated artifacts")
    rs.add_argument("--db", default=str(DEFAULT_DB_PATH))
    rs.add_argument("--runs-root", default=str(RUNS_ROOT))
    rs.add_argument("--keep-logs", action="store_true", help="Preserve runs/logs")
    rs.add_argument("--keep-reports", action="store_true", help="Preserve exports/html/dossiers")
    rs.add_argument("--keep-artifacts", action="store_true", help="Preserve exports/artifacts")
    rs.add_argument("--confirm", action="store_true", help="Required acknowledgement to perform cleanup")
    rs.add_argument("--json-summary-only", action="store_true", help="Print only JSON reset result for automation.")
    rs.add_argument("--json-only", action="store_true", help="Alias for --json-summary-only.")
    rs.add_argument("--output-file", default=None, help="Write JSON output to a file instead of stdout.")

    sm = sub.add_parser("summarize", aliases=["sum"], help="Generate a schema-validated smart summary and risk flags from noisy text")
    sm.add_argument("--target", required=True, help="Target label for the summary payload")
    sm.add_argument("--input-file", default=None, help="Optional text/HTML file to summarize")
    sm.add_argument("--text", default=None, help="Inline text payload to summarize")

    return root


def _split(val: str | None) -> list[str]:
    if not val:
        return []
    return [v.strip() for v in val.split(",") if v.strip()]


def _infer_nuclei_profile(module_tokens: list[str]) -> str | None:
    deep_presets = {"pd-full", "pd-infra-deep", "infra-deep", "recon-auto-deep", "full-spectrum-2026", "full-spectrum"}
    quick_presets = {"pd-infra", "pd-infra-quick", "recon-auto", "recon-auto-quick"}
    if any(token in deep_presets for token in module_tokens):
        return "deep"
    if any(token in quick_presets for token in module_tokens):
        return "quick"
    return None


def _configure_nuclei_profile(explicit_profile: str | None, module_tokens: list[str]) -> None:
    profile = explicit_profile or _infer_nuclei_profile(module_tokens)
    if profile:
        os.environ["HANNA_NUCLEI_PROFILE"] = profile


def _run_fail_fast_preflight(module_tokens: list[str]) -> None:
    checks = run_preflight(modules=module_tokens or None)
    if has_hard_failures(checks):
        print(format_preflight_report(checks))
        raise RuntimeError("Preflight failed for selected modules")


def _cmd_chain(args: argparse.Namespace) -> None:
    from runners.chain import ChainRunner

    module_tokens = _split(args.modules)
    metadata_file = getattr(args, "metadata_file", None)
    export_formats = _resolve_export_formats(args.export_formats, metadata_file)
    _configure_nuclei_profile(args.nuclei_profile, module_tokens)
    if not args.no_preflight:
        _run_fail_fast_preflight(module_tokens or resolve_modules(None))

    runner = ChainRunner(
        db_path=args.db,
        proxy=args.proxy,
        leak_dir=args.leak_dir,
    )
    result = _run_with_optional_stdout_capture(
        lambda: runner.run(
            exports_dir=args.exports_dir,
            target_name=args.target,
            known_phones=_split(args.phones),
            known_usernames=_split(args.usernames),
            modules=module_tokens or None,
            verified_files=args.confirmed_file,
            verify=args.verify,
            verify_all=args.verify_all,
            verify_content=args.verify_content,
            output_path=args.output,
            report_mode=args.report_mode,
        ),
        _json_only_enabled(args),
    )
    exported = _export_result_artifacts(
        result,
        export_formats,
        args.export_dir,
        metadata_file=metadata_file,
        html_path=result.extra.get("output_path") if isinstance(result.extra, dict) else None,
        report_mode=result.extra.get("report_mode") if isinstance(result.extra, dict) else None,
    )
    _emit_run_output(result, exported, print_runtime_json=args.json_summary, json_summary_only=_json_only_enabled(args))


def _cmd_aggregate(args: argparse.Namespace) -> None:
    from runners.aggregate import AggregateRunner

    module_tokens = _split(args.modules)
    metadata_file = getattr(args, "metadata_file", None)
    export_formats = _resolve_export_formats(args.export_formats, metadata_file)
    _configure_nuclei_profile(args.nuclei_profile, module_tokens)
    if not args.no_preflight:
        _run_fail_fast_preflight(module_tokens or resolve_modules(None))

    runner = AggregateRunner(
        proxy=args.proxy,
        leak_dir=args.leak_dir,
        max_workers=args.workers,
    )
    result = _run_with_optional_stdout_capture(
        lambda: runner.run(
            target_name=args.target,
            known_phones=_split(args.phones),
            known_usernames=_split(args.usernames),
            modules=module_tokens or None,
        ),
        _json_only_enabled(args),
    )
    exported = _export_result_artifacts(result, export_formats, args.export_dir, metadata_file=metadata_file)
    if not _json_only_enabled(args):
        print()
    _emit_run_output(result, exported, print_runtime_json=args.json_summary, json_summary_only=_json_only_enabled(args))


def _cmd_manual(args: argparse.Namespace) -> None:
    from runners.manual import ManualRunner

    metadata_file = getattr(args, "metadata_file", None)
    export_formats = _resolve_export_formats(args.export_formats, metadata_file)
    _configure_nuclei_profile(args.nuclei_profile, [args.module])

    runner = ManualRunner(
        proxy=args.proxy,
        leak_dir=args.leak_dir,
    )
    result = _run_with_optional_stdout_capture(
        lambda: runner.run(
            module_name=args.module,
            target_name=args.target,
            known_phones=_split(args.phones),
            known_usernames=_split(args.usernames),
        ),
        _json_only_enabled(args),
    )
    exported = _export_result_artifacts(result, export_formats, args.export_dir, metadata_file=metadata_file)
    if not _json_only_enabled(args):
        print()
    _emit_run_output(result, exported, print_runtime_json=args.json_summary, json_summary_only=_json_only_enabled(args))


def _cmd_list(args: argparse.Namespace) -> None:
    payload = _list_payload()
    if _json_only_enabled(args):
        _emit_json_payload(payload, getattr(args, "output_file", None))
        return

    print("\n=== Available Adapters ===")
    print(f"{'Name':<18} {'Region':<8} {'Lane':<6} Description")
    print("-" * 70)
    for row in payload["modules"]:
        print(f"{row['name']:<18} {row['region']:<8} {row['lane']:<6} {row['doc'][:40]}")

    print(f"\n=== Presets ({len(payload['presets'])}) ===")
    for preset in payload["presets"]:
        print(f"  {preset['name']:<20} → {', '.join(preset['modules'])}")


def _cmd_preflight(args: argparse.Namespace) -> None:
    modules = _split(args.modules) or None
    checks = run_preflight(modules=modules)
    if _json_only_enabled(args):
        _emit_json_payload(preflight_summary(checks, modules=modules))
    else:
        print(format_preflight_report(checks))
    if args.strict and has_hard_failures(checks):
        sys.exit(2)


def _cmd_reset(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise RuntimeError("reset requires --confirm")
    result = reset_workspace(
        db_path=args.db,
        runs_root=args.runs_root,
        include_logs=not args.keep_logs,
        include_reports=not args.keep_reports,
        include_artifacts=not args.keep_artifacts,
    )
    if _json_only_enabled(args):
        _emit_json_payload({
            "db": args.db,
            "runs_root": args.runs_root,
            "removed": result["removed"],
            "missing": result["missing"],
        }, getattr(args, "output_file", None))
        return
    print("Reset complete")
    for path in result["removed"]:
        print(f"  removed: {path}")
    for path in result["missing"]:
        print(f"  missing: {path}")


def _cmd_summarize(args: argparse.Namespace) -> None:
    raw_text = args.text
    if args.input_file:
        raw_text = Path(args.input_file).read_text(encoding="utf-8")
    if not raw_text:
        raise RuntimeError("summarize requires --text or --input-file")
    print(summarize_payload(args.target, raw_text))


def _cmd_tui(args: argparse.Namespace) -> None:
    try:
        from tui import HannaTUIApp, build_default_session_state
    except ImportError as exc:
        raise RuntimeError("TUI dependencies are missing. Install requirements.txt to use 'hanna tui'.") from exc

    session_state = build_default_session_state(
        target=args.target,
        modules=_split(args.modules) or None,
        report_mode=args.report_mode,
        default_mode=args.run_mode,
        manual_module=args.module,
        known_phones=_split(args.phones),
        known_usernames=_split(args.usernames),
        workers=args.workers,
        db_path=args.db,
        exports_dir=args.exports_dir,
        output_path=args.output,
        export_formats=_parse_export_formats(args.export_formats),
        export_dir=args.export_dir,
        verify=args.verify,
        verify_all=args.verify_all,
        verify_content=args.verify_content,
        proxy=args.proxy,
        leak_dir=args.leak_dir,
        no_preflight=args.no_preflight,
    )
    app = HannaTUIApp(session_state=session_state, plain=args.plain)
    app.run()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    dispatch = {
        "chain": _cmd_chain,
        "aggregate": _cmd_aggregate,
        "manual": _cmd_manual,
        "tui": _cmd_tui,
        "list": _cmd_list,
        "preflight": _cmd_preflight,
        "reset": _cmd_reset,
        "summarize": _cmd_summarize,
    }

    alias_map = {
        "ch": "chain",
        "agg": "aggregate",
        "man": "manual",
        "ui": "tui",
        "ls": "list",
        "pf": "preflight",
        "rs": "reset",
        "sum": "summarize",
    }

    handler = dispatch.get(alias_map.get(args.mode, args.mode))
    if not handler:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
