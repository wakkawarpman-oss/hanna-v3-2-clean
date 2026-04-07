from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from tui.state import SessionState


class SessionScreen(Screen[None]):
    def __init__(self, name: str, title: str) -> None:
        super().__init__(name=name)
        self.title = title
        self.session_state: SessionState | None = None

    def update_state(self, session_state: SessionState) -> None:
        self.session_state = session_state
        self.refresh_screen()

    def refresh_screen(self) -> None:
        raise NotImplementedError


class OverviewScreen(SessionScreen):
    def __init__(self) -> None:
        super().__init__(name="overview", title="Overview")

    def compose(self) -> ComposeResult:
        yield Static(id="overview-body")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        target = self.session_state.target
        execution = self.session_state.execution
        body = (
            "[Overview]\n"
            f"Entity: {target.label}\n"
            f"Phones: {', '.join(target.phones) or 'none'}\n"
            f"Emails: {', '.join(target.emails) or 'none'}\n"
            f"Usernames: {', '.join(target.usernames) or 'none'}\n\n"
            f"Mode: {execution.default_mode}\n"
            f"Current view: {self.session_state.current_view}\n"
            f"Running: {'yes' if self.session_state.running else 'no'}\n"
            f"Confidence: {self.session_state.confidence.level} ({self.session_state.confidence.score:.2f})\n"
            f"Reason: {self.session_state.confidence.reason}\n\n"
            f"Export mode: {self.session_state.export.report_mode}\n"
            f"Formats: {', '.join(self.session_state.export.formats)}\n"
            f"Export dir: {execution.export_dir or 'default'}\n"
            f"Proxy: {execution.proxy or 'direct'}\n"
            f"Leak dir: {execution.leak_dir or 'default'}\n"
            f"Verify flags: verify={execution.verify} verify_all={execution.verify_all} verify_content={execution.verify_content}\n"
            f"No preflight: {execution.no_preflight}\n"
            f"Runs root: {self.session_state.ops.runs_root}\n"
            f"DB: {self.session_state.ops.db_path}\n\n"
            "Controls: 1 overview, 2 pipeline, 3 readiness, 4 activity, e edit profile, m manual, a aggregate, c chain, r refresh readiness, q quit"
        )
        self.query_one("#overview-body", Static).update(body)


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