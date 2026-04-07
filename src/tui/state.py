from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from config import DEFAULT_DB_PATH, HTML_DIR, RUNS_ROOT
from models import RunResult
from preflight import PreflightCheck, run_preflight
from registry import MODULE_LANE, resolve_modules


@dataclass
class ConfidenceState:
    level: str
    score: float
    reason: str


@dataclass
class TargetState:
    label: str = "No target selected"
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    usernames: list[str] = field(default_factory=list)
    note: str = "Start from chain, aggregate, or manual mode to populate entity details."


@dataclass
class ModuleRunState:
    name: str
    lane: str
    status: str
    detail: str


@dataclass
class PipelineState:
    phase: str
    progress_label: str
    phase_counters: dict[str, str] = field(default_factory=dict)
    phase_timeline: list[str] = field(default_factory=list)
    modules: list[ModuleRunState] = field(default_factory=list)


@dataclass
class ExecutionConfig:
    default_mode: str = "idle"
    target: str | None = None
    resolved_modules: list[str] = field(default_factory=list)
    manual_module: str | None = None
    known_phones: list[str] = field(default_factory=list)
    known_usernames: list[str] = field(default_factory=list)
    workers: int = 4
    db_path: str = str(DEFAULT_DB_PATH)
    exports_dir: str = str(RUNS_ROOT / "exports")
    output_path: str | None = None
    export_formats: list[str] = field(default_factory=lambda: ["json", "stix", "zip"])
    export_dir: str | None = None
    report_mode: str = "shareable"
    verify: bool = False
    verify_all: bool = False
    verify_content: bool = False
    proxy: str | None = None
    leak_dir: str | None = None
    no_preflight: bool = False


@dataclass
class ReadinessState:
    checks: list[PreflightCheck] = field(default_factory=list)
    hard_failures: int = 0
    warnings: int = 0
    secrets_ready: list[str] = field(default_factory=list)
    secrets_missing: list[str] = field(default_factory=list)


@dataclass
class ExportState:
    report_mode: str
    formats: list[str]
    html_dir: str
    artifacts_dir: str


@dataclass
class OpsState:
    runs_root: str
    db_path: str
    preflight_failures: int
    preflight_warnings: int


@dataclass
class ActivityEvent:
    level: str
    text: str
    timestamp: str


@dataclass
class SessionState:
    title: str
    started_at: str
    target: TargetState
    pipeline: PipelineState
    confidence: ConfidenceState
    export: ExportState
    ops: OpsState
    execution: ExecutionConfig
    readiness: ReadinessState
    current_view: str = "overview"
    running: bool = False
    last_result_summary: list[str] = field(default_factory=list)
    activity: list[ActivityEvent] = field(default_factory=list)


def build_default_session_state(
    target: str | None = None,
    modules: list[str] | None = None,
    report_mode: str = "shareable",
    default_mode: str = "idle",
    manual_module: str | None = None,
    known_phones: list[str] | None = None,
    known_usernames: list[str] | None = None,
    workers: int = 4,
    db_path: str | None = None,
    exports_dir: str | None = None,
    output_path: str | None = None,
    export_formats: list[str] | None = None,
    export_dir: str | None = None,
    verify: bool = False,
    verify_all: bool = False,
    verify_content: bool = False,
    proxy: str | None = None,
    leak_dir: str | None = None,
    no_preflight: bool = False,
) -> SessionState:
    resolved_modules = resolve_modules(modules)
    module_names = _initial_module_names(resolved_modules, manual_module)
    module_states = [
        ModuleRunState(name=name, lane=MODULE_LANE.get(name, "fast"), status="idle", detail="queued for orchestration")
        for name in module_names
    ]
    checks = run_preflight(modules=module_names or None)
    readiness = _build_readiness_state(checks)
    started_at = datetime.now().isoformat(timespec="seconds")
    target_state = TargetState(label=target or "No target selected")
    activity = [
        ActivityEvent(level="info", text="HANNA TUI initialized", timestamp=started_at),
        ActivityEvent(level="info", text=f"Resolved {len(resolved_modules)} module(s) for operator view", timestamp=started_at),
        ActivityEvent(level="warn" if readiness.warnings else "ok", text=f"Preflight warnings: {readiness.warnings} | failures: {readiness.hard_failures}", timestamp=started_at),
    ]
    return SessionState(
        title="HANNA // OSINT & Cyber Intelligence",
        started_at=started_at,
        target=target_state,
        pipeline=PipelineState(
            phase="idle",
            progress_label=f"0 / {len(resolved_modules)} modules started",
            phase_counters={},
            phase_timeline=[],
            modules=module_states,
        ),
        confidence=ConfidenceState(
            level="medium",
            score=0.72,
            reason="Platform ready; entity not yet loaded into active cockpit state.",
        ),
        export=ExportState(
            report_mode=report_mode,
            formats=export_formats or ["json", "stix", "zip"],
            html_dir=str(HTML_DIR),
            artifacts_dir=str(RUNS_ROOT / "exports" / "artifacts"),
        ),
        ops=OpsState(
            runs_root=str(RUNS_ROOT),
            db_path=db_path or str(DEFAULT_DB_PATH),
            preflight_failures=readiness.hard_failures,
            preflight_warnings=readiness.warnings,
        ),
        execution=ExecutionConfig(
            default_mode=default_mode,
            target=target,
            resolved_modules=resolved_modules,
            manual_module=manual_module,
            known_phones=list(known_phones or []),
            known_usernames=list(known_usernames or []),
            workers=workers,
            db_path=db_path or str(DEFAULT_DB_PATH),
            exports_dir=exports_dir or str(RUNS_ROOT / "exports"),
            output_path=output_path,
            export_formats=list(export_formats or ["json", "stix", "zip"]),
            export_dir=export_dir,
            report_mode=report_mode,
            verify=verify,
            verify_all=verify_all,
            verify_content=verify_content,
            proxy=proxy,
            leak_dir=leak_dir,
            no_preflight=no_preflight,
        ),
        readiness=readiness,
        activity=activity,
    )


def refresh_readiness(state: SessionState) -> None:
    modules = active_modules_for_mode(state.execution.default_mode, state.execution)
    readiness = _build_readiness_state(run_preflight(modules=modules or None))
    state.readiness = readiness
    state.ops.preflight_failures = readiness.hard_failures
    state.ops.preflight_warnings = readiness.warnings


def apply_editor_updates(state: SessionState, payload: dict[str, str]) -> None:
    target = payload.get("target", "").strip()
    modules = _split_csv(payload.get("modules", ""))
    mode = payload.get("mode", state.execution.default_mode).strip() or state.execution.default_mode
    manual_module = payload.get("manual_module", "").strip() or None
    known_phones = _split_csv(payload.get("phones", ""))
    known_usernames = _split_csv(payload.get("usernames", ""))
    export_formats = _split_csv(payload.get("export_formats", "")) or list(state.execution.export_formats)
    export_dir = payload.get("export_dir", "").strip() or None
    exports_dir = payload.get("exports_dir", "").strip() or state.execution.exports_dir
    output_path = payload.get("output_path", "").strip() or None
    report_mode = payload.get("report_mode", state.execution.report_mode).strip() or state.execution.report_mode
    proxy = payload.get("proxy", "").strip() or None
    leak_dir = payload.get("leak_dir", "").strip() or None
    verify = _parse_bool_text(payload.get("verify", ""), state.execution.verify)
    verify_all = _parse_bool_text(payload.get("verify_all", ""), state.execution.verify_all)
    verify_content = _parse_bool_text(payload.get("verify_content", ""), state.execution.verify_content)
    no_preflight = _parse_bool_text(payload.get("no_preflight", ""), state.execution.no_preflight)
    workers_raw = payload.get("workers", "").strip()
    workers = state.execution.workers
    if workers_raw:
        try:
            workers = max(1, int(workers_raw))
        except ValueError:
            workers = state.execution.workers

    resolved_modules = resolve_modules(modules or None)
    state.execution.target = target or None
    state.execution.default_mode = mode
    state.execution.manual_module = manual_module
    state.execution.resolved_modules = resolved_modules
    state.execution.known_phones = known_phones
    state.execution.known_usernames = known_usernames
    state.execution.workers = workers
    state.execution.export_formats = export_formats
    state.execution.export_dir = export_dir
    state.execution.exports_dir = exports_dir
    state.execution.output_path = output_path
    state.execution.report_mode = report_mode
    state.execution.proxy = proxy
    state.execution.leak_dir = leak_dir
    state.execution.verify = verify
    state.execution.verify_all = verify_all
    state.execution.verify_content = verify_content
    state.execution.no_preflight = no_preflight
    state.export.report_mode = report_mode
    state.export.formats = list(export_formats)

    if target:
        state.target.label = target
    state.target.note = "Execution profile edited in TUI. Launch a run to apply the updated operator context."
    state.pipeline.phase = "idle"
    state.pipeline.phase_counters = {}
    state.pipeline.phase_timeline = []
    state.running = False
    state.last_result_summary = []
    preview_modules = active_modules_for_mode(mode, state.execution)
    state.pipeline.modules = [
        ModuleRunState(name=name, lane=MODULE_LANE.get(name, "fast"), status="idle", detail="ready from interactive profile")
        for name in preview_modules
    ]
    _recompute_progress(state)
    refresh_readiness(state)


def clear_pipeline_history(state: SessionState) -> None:
    state.pipeline.phase = "idle"
    state.pipeline.phase_counters = {}
    state.pipeline.phase_timeline = []
    state.last_result_summary = []
    _recompute_progress(state)


def reset_modules_for_run(state: SessionState, mode: str, modules: list[str]) -> None:
    state.execution.default_mode = mode
    state.pipeline.phase = "preparing"
    state.pipeline.phase_counters = {}
    state.pipeline.phase_timeline = []
    state.pipeline.modules = [
        ModuleRunState(name=name, lane=MODULE_LANE.get(name, "fast"), status="queued", detail="awaiting execution")
        for name in modules
    ]
    _recompute_progress(state)
    state.last_result_summary = []
    state.running = True


def set_phase(state: SessionState, phase: str, detail: str | None = None) -> None:
    state.pipeline.phase = phase
    _append_phase_timeline(state, phase, detail or "phase entered")
    if detail:
        state.pipeline.progress_label = detail
    else:
        _recompute_progress(state)


def update_module_status(state: SessionState, module_name: str, status: str, detail: str) -> None:
    for module in state.pipeline.modules:
        if module.name == module_name:
            module.status = status
            module.detail = detail
            break
    _recompute_progress(state)


def update_phase_counters(state: SessionState, phase: str, counters: dict[str, str | int | float]) -> None:
    normalized = ", ".join(f"{key}={value}" for key, value in counters.items())
    state.pipeline.phase_counters[phase] = normalized
    _append_phase_timeline(state, phase, normalized)


def append_activity(state: SessionState, level: str, text: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    state.activity.append(ActivityEvent(level=level, text=text, timestamp=timestamp))
    state.activity = state.activity[-40:]


def apply_run_result(state: SessionState, result: RunResult) -> None:
    state.running = False
    state.last_result_summary = result.summary_lines()
    state.target.label = result.target_name or state.target.label
    state.target.phones = list(result.new_phones)
    state.target.emails = list(result.new_emails)
    state.pipeline.phase = "completed"
    if isinstance(result.extra, dict):
        ingestion = result.extra.get("ingestion")
        if isinstance(ingestion, dict):
            update_phase_counters(state, "ingest", ingestion)
        if "clusters" in result.extra:
            update_phase_counters(state, "resolve", {"clusters": result.extra.get("clusters", 0)})
    for outcome in result.outcomes:
        detail = outcome.error or f"{len(outcome.hits)} hit(s)"
        update_module_status(state, outcome.module_name, "error" if outcome.error else "done", detail)
    state.confidence.level = "high" if result.total_hits else "medium"
    state.confidence.score = min(0.95, 0.55 + (0.05 * len(result.cross_confirmed)) + (0.02 * result.success_count))
    state.confidence.reason = f"Run {result.mode} finished with {result.total_hits} hit(s) and {len(result.cross_confirmed)} cross-confirmed observable(s)."
    if isinstance(result.extra, dict):
        html_path = result.extra.get("output_path")
        exported = result.extra.get("exports")
        if html_path:
            state.export.html_dir = str(html_path)
        if exported:
            append_activity(state, "ok", f"Artifacts exported: {', '.join(sorted(exported.keys()))}")


def active_modules_for_mode(mode: str, execution: ExecutionConfig) -> list[str]:
    if mode == "manual":
        if execution.manual_module:
            return [execution.manual_module]
        if execution.resolved_modules:
            return [execution.resolved_modules[0]]
        return []
    return list(execution.resolved_modules)


def _build_readiness_state(checks: list[PreflightCheck]) -> ReadinessState:
    secrets_ready: list[str] = []
    secrets_missing: list[str] = []
    for check in checks:
        if "token" in check.name or "key" in check.name or "secret" in check.name:
            if check.status == "ok":
                secrets_ready.append(check.name)
            else:
                secrets_missing.append(check.name)
    return ReadinessState(
        checks=checks,
        hard_failures=sum(1 for item in checks if item.status == "fail"),
        warnings=sum(1 for item in checks if item.status == "warn"),
        secrets_ready=sorted(secrets_ready),
        secrets_missing=sorted(secrets_missing),
    )


def _initial_module_names(resolved_modules: list[str], manual_module: str | None) -> list[str]:
    if manual_module:
        return [manual_module]
    return list(resolved_modules[:10])


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool_text(value: str, default: bool) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _append_phase_timeline(state: SessionState, phase: str, detail: str) -> None:
    entry = f"[{datetime.now().isoformat(timespec='seconds')}] {phase}: {detail}"
    if state.pipeline.phase_timeline and state.pipeline.phase_timeline[-1] == entry:
        return
    state.pipeline.phase_timeline.append(entry)
    state.pipeline.phase_timeline = state.pipeline.phase_timeline[-24:]


def _recompute_progress(state: SessionState) -> None:
    total = len(state.pipeline.modules)
    completed = sum(1 for module in state.pipeline.modules if module.status in {"done", "error", "timeout"})
    running = sum(1 for module in state.pipeline.modules if module.status == "running")
    queued = sum(1 for module in state.pipeline.modules if module.status == "queued")
    state.pipeline.progress_label = f"completed {completed}/{total} | running {running} | queued {queued}"