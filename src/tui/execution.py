from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from adapters.base import AdapterExecutionError, ReconHit, ReconReport, derive_runtime_issue
from config import DEFAULT_DB_PATH, RUNS_ROOT
from discovery_engine import DiscoveryEngine
from models import AdapterOutcome, RunResult
from preflight import format_preflight_report, has_hard_failures, run_preflight
from registry import MODULE_LANE, MODULES, resolve_modules
from scheduler import LaneScheduler, dedup_and_confirm
from worker import build_tasks


@dataclass
class TUIExecutionConfig:
    target: str | None = None
    modules: list[str] = field(default_factory=list)
    manual_module: str | None = None
    known_phones: list[str] = field(default_factory=list)
    known_usernames: list[str] = field(default_factory=list)
    workers: int = 4
    db_path: str = str(DEFAULT_DB_PATH)
    exports_dir: str = str(RUNS_ROOT / "exports")
    output_path: str | None = None
    export_formats: list[str] = field(default_factory=list)
    export_dir: str | None = None
    report_mode: str = "shareable"
    verify: bool = False
    verify_all: bool = False
    verify_content: bool = False
    proxy: str | None = None
    leak_dir: str | None = None
    no_preflight: bool = False


EventSink = Callable[[dict], None]


def run_mode(config: TUIExecutionConfig, mode: str, event_sink: EventSink) -> RunResult:
    _emit(event_sink, "run_started", mode=mode, target=config.target)
    modules = _resolve_mode_modules(config, mode)
    _emit(event_sink, "modules_resolved", mode=mode, modules=modules)
    _run_preflight_if_needed(config, modules, event_sink)

    if mode == "manual":
        result = _run_manual(config, modules, event_sink)
    elif mode == "aggregate":
        result = _run_aggregate(config, modules, event_sink)
    elif mode == "chain":
        result = _run_chain(config, modules, event_sink)
    else:
        raise RuntimeError(f"Unsupported TUI mode: {mode}")
    _emit(event_sink, "run_finished", mode=mode, result=result)
    return result


def _run_preflight_if_needed(config: TUIExecutionConfig, modules: list[str], event_sink: EventSink) -> None:
    checks = run_preflight(modules=modules or None)
    _emit(event_sink, "readiness", checks=checks)
    if config.no_preflight:
        _emit(event_sink, "activity", level="info", text="Preflight checks collected but fail-fast bypassed for TUI run")
        return
    if has_hard_failures(checks):
        raise RuntimeError(format_preflight_report(checks))


def _run_manual(config: TUIExecutionConfig, modules: list[str], event_sink: EventSink) -> RunResult:
    module_name = modules[0] if modules else config.manual_module
    if not module_name:
        raise RuntimeError("manual mode requires a module")
    if not config.target:
        raise RuntimeError("manual mode requires a target")
    adapter_cls = MODULES.get(module_name)
    if not adapter_cls:
        raise RuntimeError(f"Unknown module: {module_name}")

    _emit(event_sink, "phase", phase="manual", detail=f"running {module_name}")
    _emit(event_sink, "module", module=module_name, status="running", detail="manual execution started")
    started = datetime.now().isoformat()
    try:
        adapter = adapter_cls(proxy=config.proxy, timeout=15.0, leak_dir=config.leak_dir)
        hits = adapter.search(config.target, config.known_phones, config.known_usernames)
        runtime_issue = derive_runtime_issue(adapter, hits)
        outcome = AdapterOutcome(
            module_name=module_name,
            lane=MODULE_LANE.get(module_name, "fast"),
            hits=hits,
            error=runtime_issue["error"] if runtime_issue else None,
            error_kind=runtime_issue["error_kind"] if runtime_issue else None,
        )
        if runtime_issue:
            _emit(event_sink, "module", module=module_name, status="error", detail=runtime_issue["error"])
            _emit(event_sink, "activity", level="error", text=f"Manual run completed with runtime issue for {module_name}: {runtime_issue['error']}")
        else:
            _emit(event_sink, "module", module=module_name, status="done", detail=f"{len(hits)} hit(s)")
            _emit(event_sink, "activity", level="ok", text=f"Manual run completed for {module_name}: {len(hits)} hit(s)")
        known_set = set(config.known_phones)
        return RunResult(
            target_name=config.target,
            mode="manual",
            modules_run=[module_name],
            outcomes=[outcome],
            all_hits=hits,
            new_phones=sorted({h.value for h in hits if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0}),
            new_emails=sorted({h.value for h in hits if h.observable_type == "email" and h.confidence > 0}),
            started_at=started,
            finished_at=datetime.now().isoformat(),
        )
    except AdapterExecutionError as exc:
        _emit(event_sink, "module", module=module_name, status="error", detail=str(exc))
        _emit(event_sink, "activity", level="error", text=f"Manual run failed for {module_name}: {exc}")
        return RunResult(
            target_name=config.target,
            mode="manual",
            modules_run=[module_name],
            outcomes=[AdapterOutcome(
                module_name=module_name,
                lane=MODULE_LANE.get(module_name, "fast"),
                error=str(exc),
                error_kind=getattr(exc, "error_kind", "adapter_error"),
            )],
            started_at=started,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        _emit(event_sink, "module", module=module_name, status="error", detail=str(exc))
        _emit(event_sink, "activity", level="error", text=f"Manual run failed for {module_name}: {exc}")
        return RunResult(
            target_name=config.target,
            mode="manual",
            modules_run=[module_name],
            outcomes=[AdapterOutcome(module_name=module_name, lane=MODULE_LANE.get(module_name, "fast"), error=str(exc), error_kind="adapter_error")],
            started_at=started,
            finished_at=datetime.now().isoformat(),
        )


def _run_aggregate(config: TUIExecutionConfig, modules: list[str], event_sink: EventSink) -> RunResult:
    if not config.target:
        raise RuntimeError("aggregate mode requires a target")
    _emit(event_sink, "phase", phase="aggregate", detail=f"dispatching {len(modules)} module(s)")
    tasks, errors = build_tasks(
        modules,
        config.target,
        config.known_phones,
        config.known_usernames,
        config.proxy,
        10.0,
        config.leak_dir,
    )
    scheduled = LaneScheduler.dispatch(
        tasks=tasks,
        max_workers=config.workers,
        log_dir=str(RUNS_ROOT / "logs"),
        label="tui-aggregate",
        event_callback=lambda payload: _emit_scheduler_event(event_sink, payload),
    )
    deduped, cross_confirmed = dedup_and_confirm(scheduled.all_hits)
    outcomes = [
        AdapterOutcome(
            module_name=item.module_name,
            lane=item.lane,
            hits=item.hits,
            error=item.error,
            error_kind=item.error_kind,
            elapsed_sec=item.elapsed_sec,
            log_path=item.raw_log_path,
        )
        for item in scheduled.task_results
    ]
    known_set = set(config.known_phones)
    return RunResult(
        target_name=config.target,
        mode="aggregate",
        modules_run=scheduled.modules_run,
        outcomes=outcomes,
        all_hits=deduped,
        cross_confirmed=cross_confirmed,
        new_phones=sorted({h.value for h in deduped if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0}),
        new_emails=sorted({h.value for h in deduped if h.observable_type == "email" and h.confidence > 0}),
        errors=errors,
        started_at=datetime.now().isoformat(),
        finished_at=datetime.now().isoformat(),
    )


def _run_chain(config: TUIExecutionConfig, modules: list[str], event_sink: EventSink) -> RunResult:
    if not config.target and not modules:
        raise RuntimeError("chain mode requires a target or explicit modules")
    started = datetime.now().isoformat()
    exports = Path(config.exports_dir)
    output_path = config.output_path
    if not output_path:
        out_dir = exports / "html" / "dossiers"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / "discovery_dossier.html")

    engine = DiscoveryEngine(db_path=config.db_path)
    _emit(event_sink, "phase", phase="ingest", detail="ingesting metadata")
    from metadata_inputs import discover_ingest_metadata_paths

    metas = discover_ingest_metadata_paths(exports)
    ing = {"ingested": 0, "rejected": 0, "skipped": 0}
    _emit(event_sink, "phase_counters", phase="ingest", counters={"total_files": len(metas), "ingested": 0, "rejected": 0, "skipped": 0})
    for meta_path in metas:
        res = engine.ingest_metadata(meta_path)
        status = res.get("status", "unknown")
        if status == "ingested":
            ing["ingested"] += 1
        elif status == "rejected":
            ing["rejected"] += 1
        else:
            ing["skipped"] += 1
        _emit(event_sink, "phase_counters", phase="ingest", counters={"total_files": len(metas), **ing})
    _emit(event_sink, "activity", level="info", text=f"Ingest complete: {ing['ingested']} ok, {ing['rejected']} rejected, {ing['skipped']} skipped")

    _emit(event_sink, "phase", phase="resolve", detail="resolving entities")
    clusters = engine.resolve_entities()
    _emit(event_sink, "phase_counters", phase="resolve", counters={"clusters": len(clusters)})
    _emit(event_sink, "activity", level="info", text=f"Entity resolution produced {len(clusters)} cluster(s)")

    outcomes: list[AdapterOutcome] = []
    all_hits: list[ReconHit] = []
    recon_summary: dict | None = None
    if config.target or modules:
        _emit(event_sink, "phase", phase="deep_recon", detail=f"dispatching {len(modules)} module(s)")
        report = _run_deep_recon_live(engine, config, modules, event_sink)
        _emit(event_sink, "phase_counters", phase="deep_recon", counters={"modules": len(report.modules_run), "hits": len(report.hits), "errors": len(report.errors), "new_phones": len(report.new_phones), "new_emails": len(report.new_emails)})
        recon_summary = {
            "target": config.target,
            "modules_run": report.modules_run,
            "total_hits": len(report.hits),
            "new_observables": len(report.hits),
            "new_phones": report.new_phones,
            "new_emails": report.new_emails,
            "cross_confirmed": len(report.cross_confirmed),
            "errors": report.errors,
        }
        all_hits = list(report.hits)
        for item in report.outcomes:
            outcomes.append(AdapterOutcome(
                module_name=item.module_name,
                lane=item.lane,
                hits=item.hits,
                error=item.error,
                error_kind=item.error_kind,
                elapsed_sec=item.elapsed_sec,
                log_path=item.log_path,
            ))
        if report.hits:
            clusters = engine.resolve_entities()
            _emit(event_sink, "phase_counters", phase="resolve", counters={"clusters": len(clusters), "post_recon": 1})

    if config.verify or config.verify_all:
        _emit(event_sink, "phase", phase="verify_profiles", detail="verifying profile URLs")
        max_checks = 999_999 if config.verify_all else 200
        _emit(event_sink, "phase_counters", phase="verify_profiles", counters={"max_checks": max_checks, "proxy": "set" if config.proxy else "direct"})
        engine.verify_profiles(max_checks=max_checks, timeout=4.0, proxy=config.proxy)
        _emit(event_sink, "phase_counters", phase="verify_profiles", counters={"max_checks": max_checks, "completed": 1})
        _emit(event_sink, "activity", level="info", text="Profile verification complete")
    if config.verify_content:
        _emit(event_sink, "phase", phase="verify_content", detail="verifying page content")
        _emit(event_sink, "phase_counters", phase="verify_content", counters={"max_checks": 200, "proxy": "set" if config.proxy else "direct"})
        engine.verify_content(max_checks=200, timeout=8.0, proxy=config.proxy)
        _emit(event_sink, "phase_counters", phase="verify_content", counters={"max_checks": 200, "completed": 1})
        _emit(event_sink, "activity", level="info", text="Content verification complete")

    _emit(event_sink, "phase", phase="render", detail="rendering dossier")
    _emit(event_sink, "phase_counters", phase="render", counters={"output_path": output_path, "report_mode": config.report_mode})
    engine.render_graph_report(output_path=output_path, redaction_mode=config.report_mode)
    _emit(event_sink, "activity", level="ok", text=f"Dossier rendered: {output_path}")

    return RunResult(
        target_name=config.target or (clusters[0].label if clusters else "unknown"),
        mode="chain",
        modules_run=(recon_summary or {}).get("modules_run", []),
        outcomes=outcomes,
        all_hits=all_hits,
        started_at=started,
        finished_at=datetime.now().isoformat(),
        new_phones=(recon_summary or {}).get("new_phones", []),
        new_emails=(recon_summary or {}).get("new_emails", []),
        extra={
            "ingestion": ing,
            "clusters": len(clusters),
            "output_path": output_path,
            "report_mode": config.report_mode,
            "stats": engine.get_stats(),
        },
    )


def _run_deep_recon_live(
    engine: DiscoveryEngine,
    config: TUIExecutionConfig,
    modules: list[str],
    event_sink: EventSink,
) -> ReconReport:
    known_phones = [obs.value for obs in engine._all_observables if obs.obs_type == "phone"]
    known_usernames = [obs.value for obs in engine._all_observables if obs.obs_type == "username"]
    known_phones.extend(phone for phone in config.known_phones if phone)
    known_usernames.extend(user for user in config.known_usernames if user)
    known_phones = sorted(set(known_phones))
    known_usernames = sorted(set(known_usernames))

    tasks, errors = build_tasks(
        modules,
        config.target or (engine.clusters[0].label if engine.clusters else "unknown"),
        known_phones,
        known_usernames,
        config.proxy,
        10.0,
        config.leak_dir,
    )
    scheduled = LaneScheduler.dispatch(
        tasks=tasks,
        max_workers=config.workers,
        log_dir=str(RUNS_ROOT / "logs"),
        label="tui-chain",
        event_callback=lambda payload: _emit_scheduler_event(event_sink, payload),
    )
    deduped, cross_confirmed = dedup_and_confirm(scheduled.all_hits)
    outcomes = [
        ReconModuleOutcome(
            module_name=item.module_name,
            lane=item.lane,
            hits=item.hits,
            error=item.error,
            error_kind=item.error_kind,
            elapsed_sec=item.elapsed_sec,
            log_path=item.raw_log_path,
        )
        for item in scheduled.task_results
    ]
    report = ReconReport(
        target_name=config.target or "unknown",
        modules_run=scheduled.modules_run,
        hits=deduped,
        started_at=datetime.now().isoformat(),
        finished_at=datetime.now().isoformat(),
        new_phones=sorted({h.value for h in deduped if h.observable_type == "phone" and h.confidence > 0}),
        new_emails=sorted({h.value for h in deduped if h.observable_type == "email" and h.confidence > 0}),
        cross_confirmed=cross_confirmed,
        outcomes=outcomes,
        errors=errors,
    )
    _save_deep_recon_report(report, Path(RUNS_ROOT / "logs"))

    new_obs_count = 0
    for hit in report.hits:
        if hit.confidence <= 0:
            continue
        obs = engine._classify_and_register(
            value=hit.value,
            source_tool=f"deep_recon:{hit.source_module}",
            source_target=config.target or report.target_name,
            source_file=f"deep_recon:{hit.source_detail}",
            depth=1,
        )
        if obs:
            new_obs_count += 1
            engine.db.execute(
                "INSERT OR IGNORE INTO discovery_queue (obs_type, value, suggested_tools, reason, depth, state) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hit.observable_type,
                    hit.value,
                    json.dumps(["cross_verify", "getcontact"]),
                    f"Found by {hit.source_module} (conf={hit.confidence:.0%}): {hit.source_detail}",
                    1,
                    "pending",
                ),
            )
    engine.db.commit()
    _emit(event_sink, "activity", level="info", text=f"Deep recon added {new_obs_count} observable(s)")
    return report


def _resolve_mode_modules(config: TUIExecutionConfig, mode: str) -> list[str]:
    if mode == "manual":
        if config.manual_module:
            return [config.manual_module]
        if config.modules:
            return [config.modules[0]]
        return []
    return resolve_modules(config.modules or None)


def _emit_scheduler_event(event_sink: EventSink, payload: dict) -> None:
    event_type = payload.get("type")
    module_name = payload.get("module")
    if event_type == "task_queued" and module_name:
        _emit(event_sink, "module", module=module_name, status="queued", detail=f"lane={payload.get('lane')} priority=P{payload.get('priority')}")
    elif event_type == "task_done" and module_name:
        _emit(event_sink, "module", module=module_name, status="done", detail=f"{payload.get('hit_count', 0)} hit(s) in {payload.get('elapsed_sec', 0.0):.1f}s")
    elif event_type in {"task_error", "task_timeout", "task_crashed"} and module_name:
        _emit(event_sink, "module", module=module_name, status="error", detail=str(payload.get("error", "failed")))
    elif event_type == "lane_started":
        _emit(event_sink, "phase", phase=f"lane:{payload.get('lane')}", detail=f"{payload.get('task_count', 0)} task(s) dispatched")
    elif event_type == "lane_complete":
        _emit(event_sink, "activity", level="info", text=f"{payload.get('lane', 'lane')} complete: {payload.get('ok_count', 0)}/{payload.get('task_count', 0)} clean")


def _save_deep_recon_report(report: ReconReport, log_dir: Path) -> None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = log_dir.parent / f"deep_recon_{stamp}.json"
        payload = {
            "target": report.target_name,
            "modules": report.modules_run,
            "hits": [hit.to_dict() for hit in report.hits],
            "errors": report.errors,
            "started": report.started_at,
            "finished": report.finished_at,
            "new_phones": report.new_phones,
            "new_emails": report.new_emails,
            "cross_confirmed": [hit.to_dict() for hit in report.cross_confirmed],
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _emit(event_sink: EventSink, event_type: str, **payload) -> None:
    event_sink({"type": event_type, **payload})