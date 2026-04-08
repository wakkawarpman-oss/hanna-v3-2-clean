from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from smart_summary import summarize_text
from tui.state import SessionState


ALLOWED_MODES = {"idle", "manual", "aggregate", "chain"}
ALLOWED_REPORT_MODES = {"internal", "shareable", "strict"}
ALLOWED_EXPORT_FORMATS = {"json", "stix", "zip"}

ASCII_HANNA = r"""
 _   _    _    _   _ _   _    _   
| | | |  / \\  | \ | | \ | |  / \\  
| |_| | / _ \\ |  \| |  \| | / _ \\ 
|  _  |/ ___ \\| |\  | |\  |/ ___ \\
|_| |_/_/   \\_\\_| \_|_| \_/_/   \\_\\
""".strip("\n")


class AsciiHeader(Static):
    def render_header(self, session_state: SessionState) -> None:
        self.update(
            f"{ASCII_HANNA}\n"
            "[ HANNA v3.2.0 ] - Intelligence Control Plane\n"
            f"view={session_state.current_view}  phase={session_state.pipeline.phase}  prompt={session_state.prompt_status}"
        )


class TerminalGauge(Static):
    def render_gauge(self, score: float, level: str, risk_count: int) -> None:
        clamped = max(0, min(100, int(score)))
        filled = max(0, min(10, round(clamped / 10)))
        bar = "#" * filled + "." * (10 - filled)
        zone = "GREEN" if clamped < 40 else "AMBER" if clamped < 70 else "RED"
        self.update(
            "[ Security / Risk Score ]\n"
            "      .---------------------.\n"
            "   .-' 000 025 050 075 100 '-.\n"
            f"  /         [{bar}]         \\\n"
            f" |         SCORE {clamped:03d}         |\n"
            f" |   level={level.upper():<8} zone={zone:<5} |\n"
            f" |   risk_flags={risk_count:<2}             |\n"
            "  \\_________________________/"
        )


class LaneContainer(Static):
    def render_lane(self, title: str, modules: list[tuple[str, str, str]], confirmed: int, pending: int, rejected: int) -> None:
        lines = [
            f"[ {title} ]",
            f"SNR [GREEN {confirmed} CONFIRMED] | [AMBER {pending} PENDING] | [RED {rejected} NOISE]",
        ]
        if not modules:
            lines.append("  no modules assigned")
        for name, status, detail in modules[:8]:
            lines.append(f"  {_spinner(status)} {name:<16} {status:<8} {detail[:42]}")
        self.update("\n".join(lines))


class SummaryPanel(Static):
    def render_summary(self, summary_text: str, risk_tags: list[str]) -> None:
        tags = " ".join(risk_tags) or "[INFO]"
        self.update(f"[ Smart AI Summary ]\n{summary_text}\n\nTags: {tags}")


class ObservablesPanel(Static):
    def render_observables(self, session_state: SessionState) -> None:
        visible = [item for item in session_state.observables if session_state.show_rejected or item.status != "rejected"]
        hidden_count = sum(1 for item in session_state.observables if item.status == "rejected") if not session_state.show_rejected else 0
        lines = [
            "[ Entity Graph / Observables ]",
            "TYPE       VALUE                      CONF  STATE      SOURCE",
            "---------------------------------------------------------------",
        ]
        if not visible:
            lines.append("no observables yet")
        for item in visible[:10]:
            lines.append(f"{item.kind[:10]:<10} {item.value[:26]:<26} {item.confidence:>4.2f}  {item.status[:10]:<10} {item.source[:16]}")
        details_state = "open" if session_state.show_rejected else "closed"
        lines.extend([
            "",
            f"<details {details_state}> Rejected / Low Confidence [{hidden_count} hidden] - press v to toggle",
            f"Last refresh: {datetime.now().isoformat(timespec='seconds')}",
        ])
        self.update("\n".join(lines))


class SessionScreen(Screen[None]):
    def __init__(self, name: str, title: str) -> None:
        super().__init__(name=name)
        self.title = title
        self.session_state: SessionState | None = None

    def update_state(self, session_state: SessionState) -> None:
        self.session_state = session_state
        if getattr(self, "is_mounted", False):
            self.refresh_screen()

    def on_mount(self) -> None:
        if self.session_state is not None:
            self.refresh_screen()

    def refresh_screen(self) -> None:
        raise NotImplementedError


class OverviewScreen(SessionScreen):
    CSS = """
    #overview-root {
        padding: 1 1 0 1;
        height: 1fr;
    }

    #ascii-header,
    #summary-panel,
    #targets-panel,
    #fast-lane,
    #slow-lane,
    #observables-panel,
    #security-gauge {
        border: round #19f9ff;
        background: #0a0f17;
        color: #d9f8ff;
        padding: 1;
        height: auto;
    }

    #ascii-header {
        height: 8;
        color: #19f9ff;
        margin-bottom: 1;
    }

    #overview-grid {
        height: 1fr;
    }

    .dashboard-column {
        width: 1fr;
        padding-right: 1;
    }

    .dashboard-column-right {
        width: 1fr;
    }

    #summary-panel,
    #targets-panel,
    #fast-lane,
    #slow-lane,
    #observables-panel,
    #security-gauge {
        margin-bottom: 1;
    }

    #observables-panel {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(name="overview", title="Overview")

    def compose(self) -> ComposeResult:
        with Vertical(id="overview-root"):
            yield AsciiHeader(id="ascii-header")
            with Horizontal(id="overview-grid"):
                with Vertical(classes="dashboard-column"):
                    yield SummaryPanel(id="summary-panel")
                    yield Static(id="targets-panel")
                    yield LaneContainer(id="fast-lane")
                with Vertical(classes="dashboard-column-right"):
                    yield LaneContainer(id="slow-lane")
                    yield ObservablesPanel(id="observables-panel")
                    yield TerminalGauge(id="security-gauge")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        target = self.session_state.target
        execution = self.session_state.execution
        ai_input = " ".join(
            [
                target.label,
                target.note,
                " ".join(target.phones),
                " ".join(target.emails),
                " ".join(target.usernames),
                " ".join(item.text for item in self.session_state.activity[-6:]),
                " ".join(self.session_state.last_result_summary[:4]),
            ]
        ).strip()
        smart = summarize_text(target.label or "No target selected", ai_input or "No active intelligence yet.")
        risk_tags = [f"[{flag.code.upper()}]" for flag in smart.risk_flags[:3]]

        fast_modules = [
            (module.name, module.status, module.detail)
            for module in self.session_state.pipeline.modules
            if module.lane == "fast"
        ]
        slow_modules = [
            (module.name, module.status, module.detail)
            for module in self.session_state.pipeline.modules
            if module.lane == "slow"
        ]
        fast_confirmed, fast_pending, fast_rejected = _lane_status_counts(fast_modules)
        slow_confirmed, slow_pending, slow_rejected = _lane_status_counts(slow_modules)

        target_panel = (
            "[ Active Targets & Input ]\n"
            f"Name   : {target.label}\n"
            f"Phone  : {', '.join(target.phones) or ', '.join(execution.known_phones) or 'none'}\n"
            f"Email  : {', '.join(target.emails) or 'none'}\n"
            f"Domain : {_seed_domain(target.label)}\n"
            f"Users  : {', '.join(target.usernames) or ', '.join(execution.known_usernames) or 'none'}\n\n"
            f"Mode={execution.default_mode}  Workers={execution.workers}  Export={self.session_state.export.report_mode}\n"
            f"Proxy={execution.proxy or 'direct'}  DB={self.session_state.ops.db_path}"
        )

        self.query_one("#ascii-header", AsciiHeader).render_header(self.session_state)
        self.query_one("#summary-panel", SummaryPanel).render_summary(smart.summary, risk_tags)
        self.query_one("#targets-panel", Static).update(target_panel)
        self.query_one("#fast-lane", LaneContainer).render_lane("Fast Lane (P1/P3)", fast_modules, fast_confirmed, fast_pending, fast_rejected)
        self.query_one("#slow-lane", LaneContainer).render_lane("Slow Lane (P0/P2)", slow_modules, slow_confirmed, slow_pending, slow_rejected)
        self.query_one("#observables-panel", ObservablesPanel).render_observables(self.session_state)
        self.query_one("#security-gauge", TerminalGauge).render_gauge(self.session_state.confidence.score * 100, self.session_state.confidence.level, len(smart.risk_flags))


class PipelineScreen(SessionScreen):
    def __init__(self) -> None:
        super().__init__(name="pipeline", title="Pipeline")

    def compose(self) -> ComposeResult:
        yield Static(id="pipeline-body")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        lines = [
            "[Pipeline]",
            f"Phase: {self.session_state.pipeline.phase}",
            f"Progress: {self.session_state.pipeline.progress_label}",
            "",
            "Phase Counters:",
        ]
        if self.session_state.pipeline.phase_counters:
            for phase_name, detail in self.session_state.pipeline.phase_counters.items():
                lines.append(f"  {phase_name:<16} {detail}")
        else:
            lines.append("  none")
        lines.extend([
            "",
            "Phase Timeline:",
        ])
        if self.session_state.pipeline.phase_timeline:
            lines.extend(f"  {item}" for item in self.session_state.pipeline.phase_timeline[-8:])
        else:
            lines.append("  none")
        lines.extend([
            "",
            "Modules:",
        ])
        for module in self.session_state.pipeline.modules:
            lines.append(f"  {module.name:<16} {module.lane:<4} {module.status:<8} {module.detail}")
        if self.session_state.last_result_summary:
            lines.extend(["", "Last Result:"])
            lines.extend(f"  {line}" for line in self.session_state.last_result_summary[:12])
        self.query_one("#pipeline-body", Static).update("\n".join(lines))


class ReadinessScreen(SessionScreen):
    def __init__(self) -> None:
        super().__init__(name="readiness", title="Readiness")

    def compose(self) -> ComposeResult:
        yield Static(id="readiness-body")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        checks = self.session_state.readiness.checks
        lines = [
            "[Readiness]",
            f"Hard failures: {self.session_state.readiness.hard_failures}",
            f"Warnings: {self.session_state.readiness.warnings}",
            "",
            f"Secrets ready: {', '.join(self.session_state.readiness.secrets_ready) or 'none'}",
            f"Secrets missing: {', '.join(self.session_state.readiness.secrets_missing) or 'none'}",
            "",
            "Checks:",
        ]
        for check in checks:
            lines.append(f"  {check.name:<22} {check.status:<5} {check.detail}")
        self.query_one("#readiness-body", Static).update("\n".join(lines))


class ActivityScreen(SessionScreen):
    def __init__(self) -> None:
        super().__init__(name="activity", title="Activity")

    def compose(self) -> ComposeResult:
        yield Static(id="activity-body")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        lines = ["[Activity]"]
        for item in self.session_state.activity[-20:]:
            lines.append(f"[{item.timestamp}] {item.level.upper()}: {item.text}")
        self.query_one("#activity-body", Static).update("\n".join(lines))


class ConfigEditorScreen(ModalScreen[dict[str, str] | None]):
    CSS = """
    ConfigEditorScreen {
        align: center middle;
    }

    #editor-dialog {
        width: 88;
        height: auto;
        border: round #19f9ff;
        background: #10151f;
        padding: 1 2;
    }

    .editor-title {
        color: #19f9ff;
        padding-bottom: 1;
    }

    .editor-field {
        padding-top: 1;
    }

    .editor-actions {
        padding-top: 1;
        height: auto;
    }
    """

    def __init__(self, session_state: SessionState) -> None:
        super().__init__()
        self.session_state = session_state

    def compose(self) -> ComposeResult:
        execution = self.session_state.execution
        module_text = ",".join(execution.resolved_modules)
        phones_text = ",".join(execution.known_phones)
        usernames_text = ",".join(execution.known_usernames)
        export_formats_text = ",".join(execution.export_formats)
        with Vertical(id="editor-dialog"):
            yield Label("Edit Operator Profile", classes="editor-title")
            yield Label("Target", classes="editor-field")
            yield Input(value=execution.target or self.session_state.target.label, id="edit-target")
            yield Label("Modules or Presets (comma-separated)", classes="editor-field")
            yield Input(value=module_text, id="edit-modules", placeholder="full-spectrum or nuclei,naabu,httpx_probe")
            yield Label("Run Mode", classes="editor-field")
            yield Input(value=execution.default_mode, id="edit-mode", placeholder="idle | manual | aggregate | chain")
            yield Label("Manual Module", classes="editor-field")
            yield Input(value=execution.manual_module or "", id="edit-manual-module", placeholder="Used when mode=manual")
            yield Label("Known Phones", classes="editor-field")
            yield Input(value=phones_text, id="edit-phones", placeholder="+380..., +1...")
            yield Label("Known Usernames", classes="editor-field")
            yield Input(value=usernames_text, id="edit-usernames", placeholder="comma-separated usernames")
            yield Label("Workers", classes="editor-field")
            yield Input(value=str(execution.workers), id="edit-workers", placeholder="4")
            yield Label("Export Formats", classes="editor-field")
            yield Input(value=export_formats_text, id="edit-export-formats", placeholder="json,stix,zip")
            yield Label("Export Dir", classes="editor-field")
            yield Input(value=execution.export_dir or "", id="edit-export-dir", placeholder="Optional artifacts directory")
            yield Label("Exports Dir", classes="editor-field")
            yield Input(value=execution.exports_dir, id="edit-exports-dir", placeholder="Chain exports directory")
            yield Label("Output Path", classes="editor-field")
            yield Input(value=execution.output_path or "", id="edit-output-path", placeholder="Optional chain dossier path")
            yield Label("Report Mode", classes="editor-field")
            yield Input(value=execution.report_mode, id="edit-report-mode", placeholder="internal | shareable | strict")
            yield Label("Verify", classes="editor-field")
            yield Input(value=_bool_text(execution.verify), id="edit-verify", placeholder="yes/no")
            yield Label("Verify All", classes="editor-field")
            yield Input(value=_bool_text(execution.verify_all), id="edit-verify-all", placeholder="yes/no")
            yield Label("Verify Content", classes="editor-field")
            yield Input(value=_bool_text(execution.verify_content), id="edit-verify-content", placeholder="yes/no")
            yield Label("No Preflight", classes="editor-field")
            yield Input(value=_bool_text(execution.no_preflight), id="edit-no-preflight", placeholder="yes/no")
            yield Label("Proxy", classes="editor-field")
            yield Input(value=execution.proxy or "", id="edit-proxy", placeholder="socks5h://127.0.0.1:9050")
            yield Label("Leak Dir", classes="editor-field")
            yield Input(value=execution.leak_dir or "", id="edit-leak-dir", placeholder="Optional leak corpus path")
            with Horizontal(classes="editor-actions"):
                yield Button("Save", id="save", variant="success")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(
            {
                "target": self.query_one("#edit-target", Input).value,
                "modules": self.query_one("#edit-modules", Input).value,
                "mode": self.query_one("#edit-mode", Input).value,
                "manual_module": self.query_one("#edit-manual-module", Input).value,
                "phones": self.query_one("#edit-phones", Input).value,
                "usernames": self.query_one("#edit-usernames", Input).value,
                "workers": self.query_one("#edit-workers", Input).value,
                "export_formats": self.query_one("#edit-export-formats", Input).value,
                "export_dir": self.query_one("#edit-export-dir", Input).value,
                "exports_dir": self.query_one("#edit-exports-dir", Input).value,
                "output_path": self.query_one("#edit-output-path", Input).value,
                "report_mode": self.query_one("#edit-report-mode", Input).value,
                "verify": self.query_one("#edit-verify", Input).value,
                "verify_all": self.query_one("#edit-verify-all", Input).value,
                "verify_content": self.query_one("#edit-verify-content", Input).value,
                "no_preflight": self.query_one("#edit-no-preflight", Input).value,
                "proxy": self.query_one("#edit-proxy", Input).value,
                "leak_dir": self.query_one("#edit-leak-dir", Input).value,
            }
        )


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _spinner(status: str) -> str:
    if status == "running":
        return ["-", "\\", "|", "/"][datetime.now().second % 4]
    if status == "done":
        return "+"
    if status in {"error", "timeout"}:
        return "!"
    if status == "queued":
        return ">"
    return "."


def _lane_status_counts(modules: list[tuple[str, str, str]]) -> tuple[int, int, int]:
    confirmed = sum(1 for _, status, _ in modules if status == "done")
    pending = sum(1 for _, status, _ in modules if status in {"idle", "queued", "running"})
    rejected = sum(1 for _, status, _ in modules if status in {"error", "timeout"})
    return confirmed, pending, rejected


def _seed_domain(label: str) -> str:
    lowered = label.strip().lower()
    if "." in lowered and " " not in lowered:
        return lowered
    return "none"


def validate_editor_payload(payload: dict[str, str]) -> list[str]:
    errors: list[str] = []
    mode = payload.get("mode", "").strip().lower()
    report_mode = payload.get("report_mode", "").strip().lower()
    workers_raw = payload.get("workers", "").strip()
    export_formats = [item.strip().lower() for item in payload.get("export_formats", "").split(",") if item.strip()]
    manual_module = payload.get("manual_module", "").strip()
    modules = [item.strip() for item in payload.get("modules", "").split(",") if item.strip()]

    if mode and mode not in ALLOWED_MODES:
        errors.append(f"Invalid mode: {mode}")
    if report_mode and report_mode not in ALLOWED_REPORT_MODES:
        errors.append(f"Invalid report mode: {report_mode}")
    invalid_formats = [item for item in export_formats if item not in ALLOWED_EXPORT_FORMATS]
    if invalid_formats:
        errors.append(f"Invalid export formats: {', '.join(invalid_formats)}")
    if workers_raw:
        try:
            if int(workers_raw) < 1:
                errors.append("Workers must be >= 1")
        except ValueError:
            errors.append("Workers must be an integer")
    if mode == "manual" and not (manual_module or modules):
        errors.append("Manual mode requires a manual module or at least one module entry")
    return errors