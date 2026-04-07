from __future__ import annotations

from threading import Thread

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from tui.execution import TUIExecutionConfig, run_mode
from tui.screens import ActivityScreen, ConfigEditorScreen, OverviewScreen, PipelineScreen, ReadinessScreen
from tui.state import (
    SessionState,
    active_modules_for_mode,
    apply_editor_updates,
    append_activity,
    apply_run_result,
    build_default_session_state,
    refresh_readiness,
    reset_modules_for_run,
    set_phase,
    update_phase_counters,
    update_module_status,
)


class HannaTUIApp(App[None]):
    CSS = """
    Screen {
        background: #140f1d;
        color: #d9f8ff;
    }

    #topbar {
        height: 4;
        border: tall #19f9ff;
        color: #19f9ff;
        padding: 0 1;
    }

    .screen-root {
        padding: 1;
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
    ]

    def __init__(self, session_state: SessionState | None = None, plain: bool = False) -> None:
        super().__init__()
        self.session_state = session_state or build_default_session_state()
        self.plain = plain
        self._worker: Thread | None = None
        self._screens = {
            "overview": OverviewScreen(),
            "pipeline": PipelineScreen(),
            "readiness": ReadinessScreen(),
            "activity": ActivityScreen(),
        }

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._render_topbar(), id="topbar")
        yield Footer()

    def on_mount(self) -> None:
        for name, screen in self._screens.items():
            self.install_screen(screen, name=name)
            screen.update_state(self.session_state)
        self.push_screen("overview")

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

    def action_help(self) -> None:
        self.notify("Keys: 1-4 switch views, e edit profile, m manual, a aggregate, c chain, r refresh readiness, q quit", title="HANNA")

    def _render_topbar(self) -> str:
        return (
            f"{self.session_state.title}\n"
            f"Started: {self.session_state.started_at} | View: {self.session_state.current_view} | Mode: {self.session_state.execution.default_mode} | Runs root: {self.session_state.ops.runs_root}\n"
            f"{self._render_compact_chain_status()}"
        )

    def _render_compact_chain_status(self) -> str:
        if not self.session_state.pipeline.phase_counters:
            return "Chain: idle"
        compact_parts = []
        for phase_name, detail in list(self.session_state.pipeline.phase_counters.items())[-3:]:
            compact_parts.append(f"{phase_name}[{detail}]")
        timeline_tail = self.session_state.pipeline.phase_timeline[-1] if self.session_state.pipeline.phase_timeline else ""
        if timeline_tail:
            return f"Chain: {' | '.join(compact_parts)} | latest: {timeline_tail}"
        return f"Chain: {' | '.join(compact_parts)}"

    def _switch_view(self, name: str) -> None:
        self.session_state.current_view = name
        self.switch_screen(name)
        self.query_one("#topbar", Static).update(self._render_topbar())
        self._refresh_views()

    def _refresh_views(self) -> None:
        self.query_one("#topbar", Static).update(self._render_topbar())
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

    def _run_in_background(self, mode: str, config: TUIExecutionConfig) -> None:
        try:
            run_mode(config, mode, lambda event: self.call_from_thread(self._apply_event, event))
        except Exception as exc:
            self.call_from_thread(self._handle_background_error, mode, exc)

    def _handle_background_error(self, mode: str, exc: Exception) -> None:
        self.session_state.running = False
        set_phase(self.session_state, "failed", f"{mode} failed")
        append_activity(self.session_state, "error", str(exc))
        self._refresh_views()
        self.notify(str(exc), title="HANNA", severity="error")

    def _handle_editor_result(self, result: dict[str, str] | None) -> None:
        if not result:
            append_activity(self.session_state, "info", "Interactive profile edit cancelled")
            self._refresh_views()
            return
        apply_editor_updates(self.session_state, result)
        append_activity(self.session_state, "ok", "Interactive operator profile updated")
        self._refresh_views()
        self.notify("Operator profile updated", title="HANNA")

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
            set_phase(self.session_state, str(event.get("mode", "running")), "run started")
        elif event_type == "run_finished":
            result = event.get("result")
            if result is not None:
                apply_run_result(self.session_state, result)
        self._refresh_views()