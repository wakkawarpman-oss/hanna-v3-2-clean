from __future__ import annotations

import shlex
from threading import Thread
from time import sleep

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static

from exporters import export_run_result_stix, export_run_result_zip
from tui.execution import TUIExecutionConfig, run_mode
from tui.screens import ActivityScreen, ConfigEditorScreen, OverviewScreen, PipelineScreen, ReadinessScreen, validate_editor_payload
from tui.state import (
    SessionState,
    active_modules_for_mode,
    apply_editor_updates,
    append_activity,
    apply_run_result,
    build_default_session_state,
    clear_pipeline_history,
    refresh_readiness,
    reset_modules_for_run,
    set_phase,
    toggle_rejected_rows,
    update_phase_counters,
    update_module_status,
)


class HannaTUIApp(App[None]):
    CSS = """
    App {
        background: #05070b;
        color: #d9f8ff;
    }

    Screen {
        background: #05070b;
        color: #d9f8ff;
    }

    #topbar {
        dock: top;
        height: 3;
        border: tall #19f9ff;
        color: #19f9ff;
        padding: 0 1;
        background: #081019;
    }

    #command-bar {
        dock: bottom;
        height: 3;
        border: tall #19f9ff;
        background: #081019;
        padding: 0 1;
        align: left middle;
    }

    #command-prompt {
        width: 9;
        color: #19f9ff;
        content-align: center middle;
    }

    #command-input {
        width: 1fr;
        margin-right: 1;
        background: #05070b;
        color: #d9f8ff;
        border: round #19f9ff;
    }

    .export-button {
        margin-right: 1;
        min-width: 16;
    }

    #command-status {
        width: 24;
        color: #7fffd4;
        content-align: center middle;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
        ("1", "view_overview", "Overview"),
        ("2", "view_pipeline", "Pipeline"),
        ("3", "view_readiness", "Readiness"),
        ("4", "view_activity", "Activity"),
        ("m", "run_manual", "Manual"),
        ("a", "run_aggregate", "Aggregate"),
        ("c", "run_chain", "Chain"),
        ("e", "edit_profile", "Edit"),
        ("r", "refresh_readiness", "Refresh"),
        ("x", "clear_timeline", "Clear"),
        ("v", "toggle_rejected", "Toggle Noise"),
    ]

    def __init__(self, session_state: SessionState | None = None, plain: bool = False) -> None:
        super().__init__()
        self.session_state = session_state or build_default_session_state()
        self.plain = plain
        self._worker: Thread | None = None
        self._mock_worker: Thread | None = None
        self._screens = {
            "overview": OverviewScreen(),
            "pipeline": PipelineScreen(),
            "readiness": ReadinessScreen(),
            "activity": ActivityScreen(),
        }

    def compose(self) -> ComposeResult:
        yield Static(self._render_topbar(), id="topbar")
        with Horizontal(id="command-bar"):
            yield Static("hanna >", id="command-prompt")
            yield Input(placeholder='run --mode full-spectrum --target "Ivan"', id="command-input")
            yield Button("Export STIX 2.1", id="export-stix", classes="export-button")
            yield Button("Download Evidence Pack", id="export-zip", classes="export-button")
            yield Button("Generate PDF", id="export-pdf", classes="export-button")
            yield Static(self._render_command_status(), id="command-status")

    def on_mount(self) -> None:
        for name, screen in self._screens.items():
            self.install_screen(screen, name=name)
            screen.update_state(self.session_state)
        self.push_screen("overview")
        self._start_mock_lane_stream()

    def action_view_overview(self) -> None:
        self._switch_view("overview")

    def action_view_pipeline(self) -> None:
        self._switch_view("pipeline")

    def action_view_readiness(self) -> None:
        self._switch_view("readiness")

    def action_view_activity(self) -> None:
        self._switch_view("activity")

    def action_run_manual(self) -> None:
        self._start_run("manual")

    def action_run_aggregate(self) -> None:
        self._start_run("aggregate")

    def action_run_chain(self) -> None:
        self._start_run("chain")

    def action_refresh_readiness(self) -> None:
        refresh_readiness(self.session_state)
        append_activity(self.session_state, "info", "Readiness state refreshed")
        self._refresh_views()

    def action_edit_profile(self) -> None:
        if self._worker and self._worker.is_alive():
            self.notify("Wait for the active run to finish before editing the profile", severity="warning")
            return
        self.push_screen(ConfigEditorScreen(self.session_state), self._handle_editor_result)

    def action_clear_timeline(self) -> None:
        clear_pipeline_history(self.session_state)
        append_activity(self.session_state, "info", "Pipeline timeline and counters cleared")
        self._refresh_views()

    def action_toggle_rejected(self) -> None:
        toggle_rejected_rows(self.session_state)
        append_activity(self.session_state, "info", f"Rejected rows {'shown' if self.session_state.show_rejected else 'hidden'}")
        self._refresh_views()

    def action_help(self) -> None:
        self.notify("Keys: 1-4 switch views, e edit profile, m manual, a aggregate, c chain, r refresh readiness, x clear timeline, v toggle noise, q quit", title="HANNA")

    def _render_topbar(self) -> str:
        tor_status = "TOR" if self.session_state.execution.proxy and "socks" in self.session_state.execution.proxy else "DIRECT"
        ready = len(self.session_state.readiness.secrets_ready)
        total = ready + len(self.session_state.readiness.secrets_missing)
        db_size = _human_size(self.session_state.ops.db_path)
        return (
            f"HANNA v3.2.0 | Intelligence Control Plane | TOR={tor_status} | API keys={ready}/{total} | DB={db_size}\n"
            f"View={self.session_state.current_view} | Mode={self.session_state.execution.default_mode} | Runs root={self.session_state.ops.runs_root}\n"
            f"{self._render_compact_chain_status()}"
        )

    def _render_command_status(self) -> str:
        return f"[{self.session_state.prompt_status.upper()}]"

    def _render_compact_chain_status(self) -> str:
        total = len(self.session_state.pipeline.modules)
        done = sum(1 for module in self.session_state.pipeline.modules if module.status == "done")
        running = sum(1 for module in self.session_state.pipeline.modules if module.status == "running")
        queued = sum(1 for module in self.session_state.pipeline.modules if module.status == "queued")
        errors = sum(1 for module in self.session_state.pipeline.modules if module.status in {"error", "timeout"})
        phase = self.session_state.pipeline.phase
        module_summary = f"phase={phase} | modules done={done}/{total} run={running} queue={queued} err={errors}"
        if not self.session_state.pipeline.phase_counters:
            return f"Chain: {module_summary}"
        compact_parts = []
        for phase_name, detail in list(self.session_state.pipeline.phase_counters.items())[-3:]:
            compact_parts.append(f"{phase_name}[{detail}]")
        timeline_tail = self.session_state.pipeline.phase_timeline[-1] if self.session_state.pipeline.phase_timeline else ""
        if timeline_tail:
            return f"Chain: {module_summary} | {' | '.join(compact_parts)} | latest: {timeline_tail}"
        return f"Chain: {module_summary} | {' | '.join(compact_parts)}"

    def _switch_view(self, name: str) -> None:
        self.session_state.current_view = name
        self.switch_screen(name)
        self._refresh_views()

    def _refresh_views(self) -> None:
        if self.is_mounted:
            self.query_one("#topbar", Static).update(self._render_topbar())
            self.query_one("#command-status", Static).update(self._render_command_status())
        for screen in self._screens.values():
            screen.update_state(self.session_state)

    def _start_run(self, mode: str) -> None:
        if self._worker and self._worker.is_alive():
            self.notify("A TUI run is already in progress", severity="warning")
            return
        modules = active_modules_for_mode(mode, self.session_state.execution)
        reset_modules_for_run(self.session_state, mode, modules)
        append_activity(self.session_state, "info", f"Starting {mode} run from TUI")
        self._switch_view("pipeline")
        config = TUIExecutionConfig(
            target=self.session_state.execution.target or self.session_state.target.label,
            modules=list(self.session_state.execution.resolved_modules),
            manual_module=self.session_state.execution.manual_module,
            known_phones=list(self.session_state.execution.known_phones),
            known_usernames=list(self.session_state.execution.known_usernames),
            workers=self.session_state.execution.workers,
            db_path=self.session_state.execution.db_path,
            exports_dir=self.session_state.execution.exports_dir,
            output_path=self.session_state.execution.output_path,
            export_formats=list(self.session_state.execution.export_formats),
            export_dir=self.session_state.execution.export_dir,
            report_mode=self.session_state.execution.report_mode,
            verify=self.session_state.execution.verify,
            verify_all=self.session_state.execution.verify_all,
            verify_content=self.session_state.execution.verify_content,
            proxy=self.session_state.execution.proxy,
            leak_dir=self.session_state.execution.leak_dir,
            no_preflight=self.session_state.execution.no_preflight,
        )
        self._worker = Thread(target=self._run_in_background, args=(mode, config), daemon=True)
        self._worker.start()
        self._refresh_views()

    def _run_in_background(self, mode: str, config: TUIExecutionConfig) -> None:
        try:
            run_mode(config, mode, lambda event: self.call_from_thread(self._apply_event, event))
        except Exception as exc:
            self.call_from_thread(self._handle_background_error, mode, exc)

    def _handle_background_error(self, mode: str, exc: Exception) -> None:
        self.session_state.running = False
        self.session_state.prompt_status = "error"
        set_phase(self.session_state, "failed", f"{mode} failed")
        append_activity(self.session_state, "error", str(exc))
        self._refresh_views()
        self.notify(str(exc), title="HANNA", severity="error")

    def _handle_editor_result(self, result: dict[str, str] | None) -> None:
        if not result:
            append_activity(self.session_state, "info", "Interactive profile edit cancelled")
            self._refresh_views()
            return
        errors = validate_editor_payload(result)
        if errors:
            append_activity(self.session_state, "error", "; ".join(errors))
            self._refresh_views()
            self.notify("; ".join(errors), title="HANNA", severity="error")
            return
        apply_editor_updates(self.session_state, result)
        append_activity(self.session_state, "ok", "Interactive operator profile updated")
        self._refresh_views()
        self.notify("Operator profile updated", title="HANNA")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-input":
            return
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        append_activity(self.session_state, "info", f"$ {command}")
        self._execute_command(command)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "export-stix":
            self._export_last_result("stix")
        elif button_id == "export-zip":
            self._export_last_result("zip")
        elif button_id == "export-pdf":
            append_activity(self.session_state, "warn", "PDF export bridge is not wired yet")
            self.session_state.prompt_status = "pdf-pending"
            self._refresh_views()
            self.notify("PDF export is not wired yet", title="HANNA", severity="warning")

    def _execute_command(self, command: str) -> None:
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            append_activity(self.session_state, "error", f"Command parse error: {exc}")
            self.session_state.prompt_status = "parse-error"
            self._refresh_views()
            return
        if not tokens:
            return
        head = tokens[0].lower()
        if head == "run":
            self._handle_run_command(tokens[1:])
        elif head == "view" and len(tokens) > 1:
            view = tokens[1].lower()
            if view in self._screens:
                self._switch_view(view)
        elif head in {"toggle", "details"}:
            self.action_toggle_rejected()
        elif head == "export" and len(tokens) > 1:
            self._export_last_result(tokens[1].lower())
        elif head == "help":
            self.action_help()
        else:
            append_activity(self.session_state, "warn", f"Unknown command: {command}")
            self.session_state.prompt_status = "unknown-command"
            self._refresh_views()

    def _handle_run_command(self, args: list[str]) -> None:
        options = _parse_command_options(args)
        mode_token = options.get("--mode", "aggregate")
        run_mode_name = mode_token if mode_token in {"manual", "aggregate", "chain"} else "aggregate"
        modules = options.get("--modules", "")
        if mode_token not in {"manual", "aggregate", "chain"} and mode_token:
            modules = modules or mode_token
        payload = {
            "target": options.get("--target", self.session_state.execution.target or self.session_state.target.label),
            "modules": modules or ",".join(self.session_state.execution.resolved_modules),
            "mode": run_mode_name,
            "manual_module": options.get("--module", self.session_state.execution.manual_module or ""),
            "phones": options.get("--phones", ",".join(self.session_state.execution.known_phones)),
            "usernames": options.get("--usernames", ",".join(self.session_state.execution.known_usernames)),
            "workers": str(self.session_state.execution.workers),
            "export_formats": ",".join(self.session_state.execution.export_formats),
            "export_dir": self.session_state.execution.export_dir or "",
            "exports_dir": self.session_state.execution.exports_dir,
            "output_path": self.session_state.execution.output_path or "",
            "report_mode": self.session_state.execution.report_mode,
            "verify": "yes" if self.session_state.execution.verify else "no",
            "verify_all": "yes" if self.session_state.execution.verify_all else "no",
            "verify_content": "yes" if self.session_state.execution.verify_content else "no",
            "no_preflight": "yes" if self.session_state.execution.no_preflight else "no",
            "proxy": self.session_state.execution.proxy or "",
            "leak_dir": self.session_state.execution.leak_dir or "",
        }
        errors = validate_editor_payload(payload)
        if errors:
            append_activity(self.session_state, "error", "; ".join(errors))
            self.session_state.prompt_status = "invalid"
            self._refresh_views()
            return
        apply_editor_updates(self.session_state, payload)
        self.session_state.prompt_status = f"launching:{run_mode_name}"
        self._start_run(run_mode_name)

    def _export_last_result(self, artifact: str) -> None:
        result = self.session_state.latest_result
        if result is None:
            append_activity(self.session_state, "warn", f"No completed run to export as {artifact}")
            self.session_state.prompt_status = "no-export"
            self._refresh_views()
            return
        export_dir = Path(self.session_state.execution.export_dir or self.session_state.export.artifacts_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        if artifact == "stix":
            path = export_run_result_stix(result, export_dir)
        elif artifact == "zip":
            html_path = result.extra.get("output_path") if isinstance(result.extra, dict) else None
            path = export_run_result_zip(result, export_dir, html_path=html_path, report_mode=self.session_state.execution.report_mode)
        else:
            append_activity(self.session_state, "warn", f"Unsupported export command: {artifact}")
            self.session_state.prompt_status = "bad-export"
            self._refresh_views()
            return
        append_activity(self.session_state, "ok", f"Exported {artifact}: {path}")
        self.session_state.prompt_status = f"exported:{artifact}"
        self._refresh_views()

    def _start_mock_lane_stream(self) -> None:
        if self._mock_worker and self._mock_worker.is_alive():
            return
        self._mock_worker = Thread(target=self._run_mock_lane_stream, daemon=True)
        self._mock_worker.start()

    def _run_mock_lane_stream(self) -> None:
        checkpoints = [(5, 0, "running", "wayback archive sweep"), (3, 0, "done", "archive delta complete"), (2, 1, "running", "satellite frame correlation"), (2, 1, "done", "geospatial overlays matched")]
        for delay, module_index, status, detail in checkpoints:
            sleep(delay)
            self.call_from_thread(self._apply_mock_lane_update, module_index, status, detail)

    def _apply_mock_lane_update(self, module_index: int, status: str, detail: str) -> None:
        if self.session_state.running:
            return
        slow_modules = [module for module in self.session_state.pipeline.modules if module.lane == "slow"]
        if not slow_modules:
            return
        module = slow_modules[min(module_index, len(slow_modules) - 1)]
        update_module_status(self.session_state, module.name, status, detail)
        append_activity(self.session_state, "info", f"Slow lane {module.name}: {detail}")
        self._refresh_views()

    def _apply_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "phase":
            set_phase(self.session_state, str(event.get("phase", "running")), str(event.get("detail", "")))
        elif event_type == "module":
            update_module_status(
                self.session_state,
                str(event.get("module", "")),
                str(event.get("status", "running")),
                str(event.get("detail", "")),
            )
        elif event_type == "activity":
            append_activity(self.session_state, str(event.get("level", "info")), str(event.get("text", "")))
        elif event_type == "phase_counters":
            update_phase_counters(
                self.session_state,
                str(event.get("phase", "unknown")),
                dict(event.get("counters", {})),
            )
        elif event_type == "readiness":
            self.session_state.readiness.checks = list(event.get("checks", []))
            refresh_readiness(self.session_state)
        elif event_type == "modules_resolved":
            append_activity(self.session_state, "info", f"Modules resolved: {', '.join(event.get('modules', []))}")
        elif event_type == "run_started":
            self.session_state.running = True
            self.session_state.prompt_status = f"running:{event.get('mode', 'run')}"
            set_phase(self.session_state, str(event.get("mode", "running")), "run started")
        elif event_type == "run_finished":
            result = event.get("result")
            if result is not None:
                apply_run_result(self.session_state, result)
        self._refresh_views()


def _parse_command_options(tokens: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    current: str | None = None
    for token in tokens:
        if token.startswith("--"):
            current = token
            options[current] = ""
            continue
        if current is not None:
            options[current] = token
            current = None
    return options


def _human_size(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        return "0 B"
    size = float(path.stat().st_size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"