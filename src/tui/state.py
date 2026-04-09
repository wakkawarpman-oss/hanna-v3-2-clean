from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
import re

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
class ObservableState:
    kind: str
    value: str
    source: str
    confidence: float
    status: str


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
    export_formats: list[str] = field(default_factory=lambda: ["json", "metadata", "stix", "zip"])
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
class CredentialEntry:
    env_name: str
    label: str
    module: str
    value: str = ""
    enabled: bool = False


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
    observables: list[ObservableState] = field(default_factory=list)
    show_rejected: bool = False
    prompt_status: str = "ready"
    latest_result: RunResult | None = None
    next_actions: list[str] = field(default_factory=list)
    locale: str = "uk"
    credentials: list[CredentialEntry] = field(default_factory=list)


CREDENTIAL_SPECS: tuple[tuple[str, str, str], ...] = (
    ("HIBP_API_KEY", "HIBP", "hibp"),
    ("SHODAN_API_KEY", "Shodan", "shodan"),
    ("CENSYS_API_ID", "Censys ID", "censys"),
    ("CENSYS_API_SECRET", "Censys Secret", "censys"),
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot", "ua_phone"),
    ("GETCONTACT_TOKEN", "GetContact Token", "getcontact"),
    ("GETCONTACT_AES_KEY", "GetContact AES", "getcontact"),
)


def build_default_session_state(
    target: str | None = None,
    modules: list[str] | None = None,
    report_mode: str = "shareable",
    default_mode: str = "idle",
    locale: str = "uk",
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
    target_state.phones = list(known_phones or [])
    target_state.usernames = list(known_usernames or [])
    activity = [
        ActivityEvent(level="info", text="HANNA TUI initialized", timestamp=started_at),
        ActivityEvent(level="info", text=f"Resolved {len(resolved_modules)} module(s) for operator view", timestamp=started_at),
        ActivityEvent(level="warn" if readiness.warnings else "ok", text=f"Preflight warnings: {readiness.warnings} | failures: {readiness.hard_failures}", timestamp=started_at),
    ]
    credentials = _build_credential_entries()
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
            formats=export_formats or ["json", "metadata", "stix", "zip"],
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
            export_formats=list(export_formats or ["json", "metadata", "stix", "zip"]),
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
        observables=_build_seed_observables(target_state),
        locale=locale,
        credentials=credentials,
    )


def refresh_readiness(state: SessionState) -> None:
    _sync_credential_env(state)
    modules = active_modules_for_mode(state.execution.default_mode, state.execution)
    readiness = _build_readiness_state(run_preflight(modules=modules or None))
    state.readiness = readiness
    state.ops.preflight_failures = readiness.hard_failures
    state.ops.preflight_warnings = readiness.warnings


def set_credential_value(state: SessionState, env_name: str, value: str) -> CredentialEntry | None:
    entry = _find_credential_entry(state, env_name)
    if entry is None:
        return None
    entry.value = value.strip()
    if entry.enabled and not entry.value:
        entry.enabled = False
    _sync_credential_env(state)
    refresh_readiness(state)
    return entry


def toggle_credential_entry(state: SessionState, env_name: str, enabled: bool) -> CredentialEntry | None:
    entry = _find_credential_entry(state, env_name)
    if entry is None:
        return None
    entry.enabled = bool(enabled and entry.value)
    _sync_credential_env(state)
    refresh_readiness(state)
    return entry


def credential_slug(env_name: str) -> str:
    return env_name.lower().replace("_", "-")


def credential_env_from_slug(slug: str) -> str | None:
    for env_name, _, _ in CREDENTIAL_SPECS:
        if credential_slug(env_name) == slug:
            return env_name
    return None


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
    state.latest_result = None
    state.next_actions = []
    state.prompt_status = "ready"
    state.show_rejected = False
    preview_modules = active_modules_for_mode(mode, state.execution)
    state.pipeline.modules = [
        ModuleRunState(name=name, lane=MODULE_LANE.get(name, "fast"), status="idle", detail="ready from interactive profile")
        for name in preview_modules
    ]
    state.observables = _build_seed_observables(state.target)
    _recompute_progress(state)
    refresh_readiness(state)


def clear_pipeline_history(state: SessionState) -> None:
    state.pipeline.phase = "idle"
    state.pipeline.phase_counters = {}
    state.pipeline.phase_timeline = []
    state.last_result_summary = []
    state.next_actions = []
    state.prompt_status = "ready"
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
    state.next_actions = []
    state.running = True
    state.prompt_status = f"running:{mode}"


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
    state.latest_result = result
    state.next_actions = _derive_next_actions(result)
    state.prompt_status = "review-ready"
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
    if state.next_actions:
        append_activity(state, "info", f"Next actions: {', '.join(_format_action_name(action) for action in state.next_actions)}")
    state.observables = _build_observables_from_result(state.target, result)


def toggle_rejected_rows(state: SessionState) -> None:
    state.show_rejected = not state.show_rejected


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
        if any(marker in check.name for marker in ("token", "key", "secret", "api_id", "client_id")):
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


def _derive_next_actions(result: RunResult) -> list[str]:
    actions = ["review", "print", "diagnostics", "new-search"]
    actions.extend(["export-stix", "export-zip"])
    seen: set[str] = set()
    ordered: list[str] = []
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        ordered.append(action)
    return ordered


def _format_action_name(action: str) -> str:
    return action.replace("-", " ")


def _build_credential_entries() -> list[CredentialEntry]:
    entries: list[CredentialEntry] = []
    for env_name, label, module in CREDENTIAL_SPECS:
        value = os.environ.get(env_name, "").strip()
        entries.append(
            CredentialEntry(
                env_name=env_name,
                label=label,
                module=module,
                value=value,
                enabled=bool(value),
            )
        )
    return entries


def _find_credential_entry(state: SessionState, env_name: str) -> CredentialEntry | None:
    for entry in state.credentials:
        if entry.env_name == env_name:
            return entry
    return None


def _sync_credential_env(state: SessionState) -> None:
    if not state.credentials:
        return
    managed = {env_name for env_name, _, _ in CREDENTIAL_SPECS}
    for env_name in managed:
        os.environ.pop(env_name, None)
    for entry in state.credentials:
        if entry.enabled and entry.value:
            os.environ[entry.env_name] = entry.value


def _initial_module_names(resolved_modules: list[str], manual_module: str | None) -> list[str]:
    if manual_module:
        return [manual_module]
    return list(resolved_modules[:14])


def _build_seed_observables(target: TargetState) -> list[ObservableState]:
    observables: list[ObservableState] = []
    if target.label and target.label != "No target selected":
        observables.append(ObservableState(kind=_infer_seed_kind(target.label), value=target.label, source="seed", confidence=1.0, status="confirmed"))
    for phone in target.phones:
        observables.append(ObservableState(kind="phone", value=phone, source="seed", confidence=0.95, status="confirmed"))
    for email in target.emails:
        observables.append(ObservableState(kind="email", value=email, source="seed", confidence=0.95, status="confirmed"))
    for username in target.usernames:
        observables.append(ObservableState(kind="username", value=username, source="seed", confidence=0.9, status="confirmed"))
    return _dedup_observables(observables)


def _build_observables_from_result(target: TargetState, result: RunResult) -> list[ObservableState]:
    observables = _build_seed_observables(target)
    for hit in result.all_hits:
        observables.append(
            ObservableState(
                kind=hit.observable_type,
                value=hit.value,
                source=hit.source_module,
                confidence=hit.confidence,
                status=_status_for_confidence(hit.confidence),
            )
        )
    for phone in result.new_phones:
        observables.append(ObservableState(kind="phone", value=phone, source="result", confidence=0.8, status="confirmed"))
    for email in result.new_emails:
        observables.append(ObservableState(kind="email", value=email, source="result", confidence=0.8, status="confirmed"))
    return _dedup_observables(observables)


def _dedup_observables(values: list[ObservableState]) -> list[ObservableState]:
    best: dict[tuple[str, str], ObservableState] = {}
    for item in values:
        key = (item.kind, item.value)
        current = best.get(key)
        if current is None or item.confidence >= current.confidence:
            best[key] = item
    return sorted(best.values(), key=lambda item: (item.status == "rejected", -item.confidence, item.kind, item.value))


def _status_for_confidence(confidence: float) -> str:
    if confidence >= 0.75:
        return "confirmed"
    if confidence >= 0.45:
        return "candidate"
    return "rejected"


def _infer_seed_kind(value: str) -> str:
    lowered = value.lower().strip()
    if "@" in lowered:
        return "email"
    if re.search(r"\d", lowered) and ("+" in lowered or lowered.replace(" ", "").isdigit()):
        return "phone"
    if "." in lowered and " " not in lowered:
        return "domain"
    return "name"


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