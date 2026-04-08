from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from smart_summary import summarize_text
from tui.state import ExecutionConfig, SessionState, TargetState


ALLOWED_MODES = {"idle", "manual", "aggregate", "chain"}
ALLOWED_REPORT_MODES = {"internal", "shareable", "strict"}
ALLOWED_EXPORT_FORMATS = {"json", "metadata", "stix", "zip"}

ASCII_HANNA = r"""
██╗  ██╗ █████╗ ███╗   ██╗███╗   ██╗ █████╗
██║  ██║██╔══██╗████╗  ██║████╗  ██║██╔══██╗
███████║███████║██╔██╗ ██║██╔██╗ ██║███████║
██╔══██║██╔══██║██║╚██╗██║██║╚██╗██║██╔══██║
██║  ██║██║  ██║██║ ╚████║██║ ╚████║██║  ██║
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═══╝╚═╝  ╚═╝
""".strip("\n")


class AsciiHeader(Static):
    def render_header(self, session_state: SessionState) -> None:
        ready = len(session_state.readiness.secrets_ready)
        total = ready + len(session_state.readiness.secrets_missing)
        time_label = session_state.started_at.replace("T", " ")[:16]
        self.update(
            f"[bold #00ffcc]{ASCII_HANNA}[/]   [bold #ff44aa]OSINT & КІБЕРРОЗВІДКА[/]\n"
            f"[#7fdbff]{time_label}[/] | [#ffcc00]view={session_state.current_view}[/] | [#ff6bdf]mode={session_state.execution.default_mode}[/] | [#00ff88]phase={session_state.pipeline.phase}[/]\n"
            f"[#19f9ff]keys={ready}/{total}[/] | [#ff9f6b]warnings={session_state.readiness.warnings}[/] | [#ff4466]failures={session_state.readiness.hard_failures}[/] | [#c89bff]prompt={session_state.prompt_status}[/]"
        )


class TargetDossierPanel(Static):
    def render_target(self, session_state: SessionState) -> None:
        target = session_state.target
        execution = session_state.execution
        primary_username = (target.usernames or execution.known_usernames or ["none"])[0]
        primary_phone = (target.phones or execution.known_phones or ["none"])[0]
        primary_email = (target.emails or [_infer_email_hint(target.label)])[0]
        domain = _infer_primary_domain(target, execution)
        lines = [
            "TARGET ENTITY",
            "     .-''''-.",
            "   .'  .--.  '.",
            "  /   /    \\   \\",
            "  |   | () |   |",
            "  |   | /\\ |   |",
            "  \\   \\__/   /",
            "   '.      .'",
            "     '-..-'",
            "",
            "Priority target:",
            f"Username : {primary_username}",
            f"Phone    : {_mask_phone(primary_phone)}",
            f"Email    : {_shorten(primary_email, 22)}",
            f"Domain   : {_shorten(domain, 22)}",
            f"Profile  : {_shorten(target.label, 22)}",
            "",
            f"Mode={execution.default_mode} | workers={execution.workers} | report={session_state.export.report_mode}",
            f"Proxy={execution.proxy or 'direct'}",
        ]
        self.update("\n".join(lines))


class HeatmapPanel(Static):
    def render_heatmap(self, session_state: SessionState) -> None:
        cells = _heatmap_values(session_state)
        rows = [
            "SIGNAL HEATMAP",
            "  confidence lattice",
            "",
        ]
        for row in cells:
            rows.append("  " + " ".join(_heat_cell(value) for value in row))
        rows.extend(
            [
                "",
                f"  observables={len(session_state.observables):02d} | activity={len(session_state.activity[-10:]):02d}",
            ]
        )
        self.update("\n".join(rows))


class ThreatMeterPanel(Static):
    def render_meter(self, score: float, level: str, risk_count: int) -> None:
        clamped = max(0, min(100, int(score)))
        steps = 6
        filled = max(0, min(steps, round((clamped / 100) * steps)))
        rows = ["THREAT LEVEL"]
        for index in range(steps, 0, -1):
            marker = "██" if index <= filled else "  "
            rows.append(f"{index:>2} |{marker}|")
        rows.extend(
            [
                "   +--+",
                f"score {clamped:03d}",
                f"lvl   {level.upper()[:4]}",
                f"flags {risk_count:02d}",
            ]
        )
        self.update("\n".join(rows))


class LaneContainer(Static):
    def render_lane(self, title: str, modules: list[tuple[str, str, str]], confirmed: int, pending: int, rejected: int) -> None:
        lines = [
            f"[bold #ffcc00][ {title} ][/]",
            f"SNR [bold #00ff88]{confirmed} confirmed[/] | [bold #ffcc00]{pending} pending[/] | [bold #ff4466]{rejected} noise[/]",
        ]
        if not modules:
            lines.append("  no modules assigned")
        for name, status, detail in modules[:8]:
            lines.append(f"  {_spinner(status)} {name:<16} {_status_label(status):<10} {_shorten(detail, 36)}")
        self.update("\n".join(lines))


class PipelineMonitorPanel(Static):
    def render_pipeline(self, session_state: SessionState) -> None:
        phase = session_state.pipeline.phase
        progress = session_state.pipeline.progress_label
        lines = [
            "ORCHESTRATION PIPELINES",
            f"Adapter / pipeline status | phase={phase}",
            "",
        ]
        if not session_state.pipeline.modules:
            lines.append("  no modules resolved")
        for module in session_state.pipeline.modules[:9]:
            lines.append(
                f"{module.name:<16} {_status_label(module.status):<10} {_module_meter(module.status)} {_shorten(module.detail, 26)}"
            )
        lines.extend(
            [
                "",
                "      [====>] > ingestion > normalization > entity-resolution --> reporting",
                f"progress: {progress}",
            ]
        )
        self.update("\n".join(lines))


class SummaryPanel(Static):
    def render_summary(self, summary_text: str, risk_tags: list[str]) -> None:
        tags = " ".join(risk_tags) or "[INFO]"
        self.update(f"ANALYST BRIEF\n{summary_text}\n\nThreat tags: {tags}")


class ObservablesPanel(Static):
    def render_observables(self, session_state: SessionState) -> None:
        visible = [item for item in session_state.observables if session_state.show_rejected or item.status != "rejected"]
        hidden_count = sum(1 for item in session_state.observables if item.status == "rejected") if not session_state.show_rejected else 0
        lines = [
            "RECENT KEY FINDINGS",
            "TYPE       VALUE                      CONF  STATE       SOURCE",
            "---------------------------------------------------------------",
        ]
        if not visible:
            lines.append("no observables yet")
        for item in visible[:8]:
            lines.append(
                f"{item.kind[:10]:<10} {_shorten(item.value, 26):<26} {item.confidence:>4.2f}  {_status_plain(item.status):<11} {item.source[:16]}"
            )
        lines.extend([
            "",
            f"Rejected / low confidence hidden: {hidden_count} | press v to toggle noise rows",
            f"Last refresh: {datetime.now().isoformat(timespec='seconds')}",
        ])
        self.update("\n".join(lines))


class SystemPulsePanel(Static):
    def render_system(self, session_state: SessionState) -> None:
        modules = session_state.pipeline.modules
        done = sum(1 for module in modules if module.status == "done")
        running = sum(1 for module in modules if module.status == "running")
        queued = sum(1 for module in modules if module.status in {"queued", "idle"})
        failed = sum(1 for module in modules if module.status in {"error", "timeout"})
        pulses = _spark_bars([queued, running, done, failed, len(session_state.activity[-8:]), session_state.readiness.warnings])
        lines = [
            "SYSTEM STATE",
            f"Started  {session_state.started_at.replace('T', ' ')[:19]}",
            f"Runs root {_shorten(session_state.ops.runs_root, 28)}",
            f"DB       {_shorten(session_state.ops.db_path, 28)}",
            "",
            f"signals  {pulses}",
            f"modules  done={done} run={running} queue={queued} fail={failed}",
            f"secrets  ready={len(session_state.readiness.secrets_ready)} missing={len(session_state.readiness.secrets_missing)}",
        ]
        self.update("\n".join(lines))


class ActivityFeedPanel(Static):
    def render_activity(self, session_state: SessionState) -> None:
        lines = ["ACTIVITY FEED"]
        if not session_state.activity:
            lines.append("no activity yet")
        for item in session_state.activity[-10:]:
            lines.append(f"[{item.timestamp[11:16]}] {_level_badge(item.level)} {_shorten(item.text, 54)}")
        self.update("\n".join(lines))


class CommandLegendPanel(Static):
    def render_legend(self) -> None:
        self.update(
            "QUICK COMMANDS\n"
            "/ focus command line\n"
            "? help\n"
            "e edit operator profile\n"
            "m manual | a aggregate | c chain\n"
            "q quit"
        )


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
        background: #07060d;
    }

    #ascii-header,
    #summary-panel,
    #target-panel,
    #pipeline-monitor,
    #fast-lane,
    #system-panel,
    #observables-panel,
    #heatmap-panel,
    #threat-meter,
    #activity-feed,
    #command-legend {
        border: round #19f9ff;
        background: #100915;
        color: #d9f8ff;
        padding: 1;
        height: auto;
    }

    #ascii-header {
        height: 12;
        color: #00ffcc;
        margin-bottom: 1;
        background: #0a0816;
        border: round #00ffcc;
    }

    #overview-grid {
        height: 1fr;
    }

    #left-column {
        width: 36;
        padding-right: 1;
    }

    #center-column {
        width: 1fr;
        padding: 0 1;
    }

    #right-column {
        width: 40;
    }

    #summary-panel,
    #target-panel,
    #pipeline-monitor,
    #fast-lane,
    #system-panel,
    #observables-panel,
    #heatmap-panel,
    #threat-meter,
    #activity-feed,
    #command-legend {
        margin-bottom: 1;
    }

    #target-panel {
        height: 20;
        border: round #7fdbff;
        background: #0c0a18;
    }

    #command-legend {
        height: 8;
        border: round #ffcc00;
        background: #0e0b14;
        color: #ffcc00;
    }

    #pipeline-monitor {
        height: 12;
        border: round #ff44aa;
        background: #120812;
    }

    #summary-panel {
        height: 11;
        border: round #c89bff;
        background: #0e0819;
    }

    #fast-lane {
        height: 11;
        border: round #ff9f6b;
        background: #120d12;
    }

    #system-panel {
        height: 10;
        border: round #00ff88;
        background: #081210;
    }

    #observables-panel {
        height: 1fr;
        border: round #ff6bdf;
        background: #0d0913;
    }

    #activity-feed {
        height: 1fr;
        border: round #7fdbff;
        background: #0b1018;
    }

    #risk-row {
        height: 12;
    }

    #heatmap-panel {
        width: 1fr;
        height: 10;
        border: round #ff4466;
        background: #130c12;
        margin-right: 1;
    }

    #threat-meter {
        width: 14;
        border: round #ffcc00;
        background: #14100c;
        height: 10;
    }
    """

    def __init__(self) -> None:
        super().__init__(name="overview", title="Overview")

    def compose(self) -> ComposeResult:
        with Vertical(id="overview-root"):
            yield AsciiHeader(id="ascii-header")
            with Horizontal(id="overview-grid"):
                with Vertical(id="left-column"):
                    yield TargetDossierPanel(id="target-panel")
                    yield ObservablesPanel(id="observables-panel")
                    yield CommandLegendPanel(id="command-legend")
                with Vertical(id="center-column"):
                    yield PipelineMonitorPanel(id="pipeline-monitor")
                    yield SummaryPanel(id="summary-panel")
                    yield LaneContainer(id="fast-lane")
                with Vertical(id="right-column"):
                    yield SystemPulsePanel(id="system-panel")
                    with Horizontal(id="risk-row"):
                        yield HeatmapPanel(id="heatmap-panel")
                        yield ThreatMeterPanel(id="threat-meter")
                    yield ActivityFeedPanel(id="activity-feed")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        target = self.session_state.target
        ai_input = _build_summary_input(self.session_state)
        smart = summarize_text(target.label or "No target selected", ai_input or "No active intelligence yet.")
        risk_tags = [f"[{flag.code.upper()}]" for flag in smart.risk_flags[:3]]

        fast_modules = [
            (module.name, module.status, module.detail)
            for module in self.session_state.pipeline.modules
            if module.lane == "fast"
        ]
        fast_confirmed, fast_pending, fast_rejected = _lane_status_counts(fast_modules)

        self.query_one("#ascii-header", AsciiHeader).render_header(self.session_state)
        self.query_one("#target-panel", TargetDossierPanel).render_target(self.session_state)
        self.query_one("#pipeline-monitor", PipelineMonitorPanel).render_pipeline(self.session_state)
        self.query_one("#summary-panel", SummaryPanel).render_summary(smart.summary, risk_tags)
        self.query_one("#fast-lane", LaneContainer).render_lane("Fast Lane (P1/P3)", fast_modules, fast_confirmed, fast_pending, fast_rejected)
        self.query_one("#system-panel", SystemPulsePanel).render_system(self.session_state)
        self.query_one("#observables-panel", ObservablesPanel).render_observables(self.session_state)
        self.query_one("#heatmap-panel", HeatmapPanel).render_heatmap(self.session_state)
        self.query_one("#threat-meter", ThreatMeterPanel).render_meter(self.session_state.confidence.score * 100, self.session_state.confidence.level, len(smart.risk_flags))
        self.query_one("#activity-feed", ActivityFeedPanel).render_activity(self.session_state)
        self.query_one("#command-legend", CommandLegendPanel).render_legend()


class PipelineScreen(SessionScreen):
    CSS = """
    #pipeline-body {
        margin: 1;
        padding: 1 2;
        border: round #ff7a8e;
        background: #100915;
        color: #f2f1f5;
        height: 1fr;
    }
    """

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
    CSS = """
    #readiness-body {
        margin: 1;
        padding: 1 2;
        border: round #20d5ff;
        background: #0b1219;
        color: #f2f1f5;
        height: 1fr;
    }
    """

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
    CSS = """
    #activity-body {
        margin: 1;
        padding: 1 2;
        border: round #20d5ff;
        background: #091018;
        color: #f2f1f5;
        height: 1fr;
    }
    """

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
            yield Input(value=export_formats_text, id="edit-export-formats", placeholder="json,metadata,stix,zip")
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


def _shorten(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(0, width - 3)] + "..."


def _status_plain(status: str) -> str:
    labels = {
        "done": "confirmed",
        "running": "running",
        "queued": "queued",
        "idle": "idle",
        "error": "error",
        "timeout": "timeout",
        "candidate": "candidate",
        "confirmed": "confirmed",
        "rejected": "rejected",
    }
    return labels.get(status, status)


def _status_label(status: str) -> str:
    labels = {
        "done": "COMPLETE",
        "running": "SCANNING",
        "queued": "QUEUED",
        "idle": "STAGED",
        "error": "ERROR",
        "timeout": "TIMEOUT",
    }
    return labels.get(status, status.upper())


def _module_meter(status: str) -> str:
    meters = {
        "done": "[====>]",
        "running": "[..>> ]",
        "queued": "[  .. ]",
        "idle": "[ ....]",
        "error": "[ !! ]",
        "timeout": "[ xx ]",
    }
    return meters.get(status, "[ ....]")


def _spark_bars(values: list[int]) -> str:
    bars = "▁▂▃▄▅▆▇█"
    top = max(max(values, default=0), 1)
    return "".join(bars[min(len(bars) - 1, round((value / top) * (len(bars) - 1)))] for value in values)


def _level_badge(level: str) -> str:
    badges = {
        "ok": "[OK]",
        "info": "[AI]",
        "warn": "[WRN]",
        "error": "[ERR]",
    }
    return badges.get(level, f"[{level[:3].upper()}]")


def _mask_phone(value: str) -> str:
    digits = [char for char in value if char.isdigit()]
    if len(digits) < 6:
        return value
    return f"+{''.join(digits[:3])} ** *** **{''.join(digits[-2:])}"


def _infer_email_hint(label: str) -> str:
    seed = label.strip().lower().replace(" ", ".")
    if not seed or seed == "no target selected":
        return "none"
    if "@" in seed:
        return seed
    return f"{seed}@intel.local"


def _infer_primary_domain(target: TargetState, execution: ExecutionConfig) -> str:
    if target.emails:
        email = target.emails[0]
        if "@" in email:
            return email.split("@", 1)[1]
    if execution.known_usernames:
        return "identity.local"
    return _seed_domain(target.label)


def _build_summary_input(session_state: SessionState) -> str:
    target = session_state.target
    return " ".join(
        [
            target.label,
            target.note,
            " ".join(target.phones),
            " ".join(target.emails),
            " ".join(target.usernames),
            " ".join(item.text for item in session_state.activity[-6:]),
            " ".join(session_state.last_result_summary[:4]),
        ]
    ).strip()


def _heatmap_values(session_state: SessionState) -> list[list[float]]:
    observables = session_state.observables[:12]
    values = [item.confidence for item in observables]
    while len(values) < 12:
        values.append(0.15 if len(values) % 3 else 0.35)
    return [values[index:index + 4] for index in range(0, 12, 4)]


def _heat_cell(value: float) -> str:
    if value >= 0.85:
        return "██"
    if value >= 0.65:
        return "▓▓"
    if value >= 0.45:
        return "▒▒"
    if value >= 0.25:
        return "░░"
    return ".."


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