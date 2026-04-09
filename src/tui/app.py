from __future__ import annotations

import re
import shlex
from threading import Thread
from time import sleep

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static, Switch

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
    credential_slug,
    credential_env_from_slug,
    refresh_readiness,
    reset_modules_for_run,
    set_credential_value,
    set_phase,
    toggle_credential_entry,
    toggle_rejected_rows,
    update_phase_counters,
    update_module_status,
)


STARTUP_BANNER_TEXT = "Search-first command center active. Use the prompt above for phone, email, username, review, diagnostics, print, and export actions. Press / to refocus input."
STARTUP_NOTIFY_TEXT = "HANNA command center ready. Use plain-language prompts in the search bar above. Press / if focus leaves the input."
HELP_NOTIFICATION_TEXT = "Keys: / focus search, 1-4 switch views, e edit profile, m manual, a aggregate, c chain, r refresh readiness, x clear timeline, v toggle noise, q quit | prompt shortcuts: phone, email, username, review, diagnostics, print, keys"

NEXT_ACTION_LABELS = {
    "review": "review",
    "print": "print",
    "diagnostics": "diagnostics",
    "new-search": "new search",
    "export-stix": "export stix",
    "export-zip": "export zip",
}

SUPPORTED_LOCALES = {"uk", "en", "pl", "lt"}
LOCALE_ALIASES = {"ua": "uk", "uk": "uk", "en": "en", "pl": "pl", "lt": "lt"}

CREDENTIAL_FOCUS_TARGETS = {
    "censys": "CENSYS_API_ID",
    "shodan": "SHODAN_API_KEY",
    "hibp": "HIBP_API_KEY",
    "telegram": "TELEGRAM_BOT_TOKEN",
    "getcontact": "GETCONTACT_TOKEN",
}

COMMAND_BOARD_TRANSLATIONS = {
    "uk": {
        "title": "ЦЕНТР КОМАНД",
        "hint": "Мова: українська | змінити: lang uk|en|pl|lt",
        "subtitle": "Пишіть людською мовою. HANNA перетворює фразу на пошук, огляд результатів, діагностику або експорт.",
        "chips": ["phone +380...", "email name@example.com", "username target", "review", "diagnostics", "print"],
        "columns": [
            ("Пошук", ["phone +380...", "email name@example.com", "username target"]),
            ("Огляд", ["review", "diagnostics", "activity"]),
            ("Дії", ["print", "export stix", "export zip"]),
            ("Система", ["new search", "keys", "lang en|pl|lt"]),
        ],
    },
    "en": {
        "title": "COMMAND CENTER",
        "hint": "Language: English | switch with: lang uk|en|pl|lt",
        "subtitle": "Type natural prompts. HANNA turns them into search, review, diagnostics, and export actions.",
        "chips": ["phone +380...", "email name@example.com", "username target", "review", "diagnostics", "print"],
        "columns": [
            ("Search", ["phone +380...", "email name@example.com", "username target"]),
            ("Review", ["review", "diagnostics", "activity"]),
            ("Actions", ["print", "export stix", "export zip"]),
            ("System", ["new search", "keys", "lang uk|pl|lt"]),
        ],
    },
    "pl": {
        "title": "CENTRUM KOMEND",
        "hint": "Jezyk: polski | zmiana: lang uk|en|pl|lt",
        "subtitle": "Pisz naturalnie. HANNA zamienia fraze na wyszukiwanie, przeglad wynikow, diagnostyke albo eksport.",
        "chips": ["phone +380...", "email name@example.com", "username target", "review", "diagnostics", "print"],
        "columns": [
            ("Szukaj", ["phone +380...", "email name@example.com", "username target"]),
            ("Przeglad", ["review", "diagnostics", "activity"]),
            ("Akcje", ["print", "export stix", "export zip"]),
            ("System", ["new search", "keys", "lang uk|en|lt"]),
        ],
    },
    "lt": {
        "title": "KOMANDU CENTRAS",
        "hint": "Kalba: lietuviu | keisti: lang uk|en|pl|lt",
        "subtitle": "Rasykite naturaliai. HANNA pavercia fraze i paieska, rezultatu perziura, diagnostika arba eksporta.",
        "chips": ["phone +380...", "email name@example.com", "username target", "review", "diagnostics", "print"],
        "columns": [
            ("Paieska", ["phone +380...", "email name@example.com", "username target"]),
            ("Perziura", ["review", "diagnostics", "activity"]),
            ("Veiksmai", ["print", "export stix", "export zip"]),
            ("Sistema", ["new search", "keys", "lang uk|en|pl"]),
        ],
    },
}

PHONE_INTENT_PREFIXES = (
    "phone",
    "find by phone",
    "check phone",
    "search phone",
    "номер",
    "знайди по номеру",
    "перевір номер",
    "шукати номер",
    "numer",
    "szukaj po numerze",
    "sprawdz numer",
    "numeris",
    "ieskok pagal numeri",
    "tikrink numeri",
)

EMAIL_INTENT_PREFIXES = (
    "email",
    "check email",
    "find email",
    "search email",
    "перевір email",
    "знайди email",
    "перевір пошту",
    "sprawdz email",
    "szukaj email",
    "tikrink email",
    "ieskok email",
)

USERNAME_INTENT_PREFIXES = (
    "username",
    "user",
    "check username",
    "find username",
    "search username",
    "перевір username",
    "знайди username",
    "перевір юзернейм",
    "sprawdz username",
    "szukaj username",
    "tikrink username",
    "ieskok username",
)

INTENT_EXACT_COMMANDS = {
    "review": "view overview",
    "results": "view overview",
    "show results": "view overview",
    "show findings": "view overview",
    "show overview": "view overview",
    "покажи результати": "view overview",
    "покажи знахідки": "view overview",
    "покажи головне": "view overview",
    "pokaz wyniki": "view overview",
    "pokaz glowny ekran": "view overview",
    "rodyk rezultatus": "view overview",
    "rodyk pagrindini": "view overview",
    "diagnostics": "view readiness",
    "readiness": "view readiness",
    "show diagnostics": "view readiness",
    "show readiness": "view readiness",
    "чому нічого не знайдено": "view readiness",
    "покажи діагностику": "view readiness",
    "покажи готовність": "view readiness",
    "pokaz diagnostyke": "view readiness",
    "pokaz gotowosc": "view readiness",
    "rodyk diagnostika": "view readiness",
    "rodyk parengti": "view readiness",
    "activity": "view activity",
    "logs": "view activity",
    "show activity": "view activity",
    "show log": "view activity",
    "покажи активність": "view activity",
    "покажи лог": "view activity",
    "pokaz aktywnosc": "view activity",
    "pokaz log": "view activity",
    "rodyk aktyvuma": "view activity",
    "rodyk zurnala": "view activity",
    "pipeline": "view pipeline",
    "show pipeline": "view pipeline",
    "show progress": "view pipeline",
    "покажи прогрес": "view pipeline",
    "покажи пайплайн": "view pipeline",
    "pokaz postep": "view pipeline",
    "pokaz pipeline": "view pipeline",
    "rodyk eiga": "view pipeline",
    "new search": "focus",
    "keys": "credentials",
    "credentials": "credentials",
    "api keys": "credentials",
    "show keys": "credentials",
    "show credentials": "credentials",
    "покажи ключі": "credentials",
    "ключі": "credentials",
    "klucze": "credentials",
    "pokaz klucze": "credentials",
    "raktai": "credentials",
    "rodyk raktus": "credentials",
    "focus": "focus",
    "search": "focus",
    "stix": "export stix",
    "zip": "export zip",
    "print": "export zip",
    "print report": "export zip",
    "друк": "export zip",
    "друк звіту": "export zip",
    "druk": "export zip",
    "druk raportu": "export zip",
    "spausdinti": "export zip",
    "spausdinti ataskaita": "export zip",
}


class HannaTUIApp(App[None]):
    CSS = """
    App {
        background: #07060d;
        color: #e8f7ff;
    }

    Screen {
        background: #07060d;
        color: #e8f7ff;
    }

    #topbar {
        dock: top;
        height: 4;
        border: tall #00ffcc;
        color: #00ffcc;
        padding: 0 1;
        background: #04070d;
    }

    #command-board {
        dock: top;
        height: 10;
        border: tall #19f9ff;
        color: #dffcff;
        padding: 0 1;
        background: #071019;
    }

    #command-bar {
        dock: top;
        height: 4;
        border: tall #7fdbff;
        background: #050b12;
        padding: 0 1;
        align: left middle;
    }

    #startup-banner {
        dock: bottom;
        height: 2;
        border: tall #ffcc00;
        background: #130f08;
        color: #ffcc00;
        padding: 0 1;
        content-align: left middle;
    }

    #command-prompt {
        width: 14;
        color: #00ffcc;
        content-align: center middle;
    }

    #command-input {
        width: 1fr;
        margin-right: 1;
        background: #030508;
        color: #e8f7ff;
        border: round #7fdbff;
    }

    .export-button {
        margin-right: 1;
        min-width: 13;
        background: #0c1118;
        color: #f2f1f5;
        border: round #19f9ff;
    }

    #command-status {
        width: 24;
        color: #00ff88;
        content-align: center middle;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
        ("/", "focus_command", "Command"),
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
        self._suspend_credential_events = False
        self._screens = {
            "overview": OverviewScreen(),
            "pipeline": PipelineScreen(),
            "readiness": ReadinessScreen(),
            "activity": ActivityScreen(),
        }

    def compose(self) -> ComposeResult:
        yield Static(self._render_topbar(), id="topbar")
        yield Static(self._render_command_board(), id="command-board")
        with Horizontal(id="command-bar"):
            yield Static("search >", id="command-prompt")
            yield Input(placeholder="phone +380... | email analyst@example.com | username target | review", id="command-input")
            yield Button("Export STIX 2.1", id="export-stix", classes="export-button")
            yield Button("Download Evidence Pack (ZIP)", id="export-zip", classes="export-button")
            yield Button("Generate PDF", id="export-pdf", classes="export-button")
            yield Static(self._render_command_status(), id="command-status")
        yield Static(self._render_startup_banner(), id="startup-banner")

    def on_mount(self) -> None:
        for name, screen in self._screens.items():
            self.install_screen(screen, name=name)
            screen.update_state(self.session_state)
        self.push_screen("overview")
        self._focus_command_input()
        self.notify(STARTUP_NOTIFY_TEXT, title="HANNA")
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
        self.notify(HELP_NOTIFICATION_TEXT, title="HANNA")

    def action_focus_command(self) -> None:
        self._focus_command_input()

    def action_focus_credentials(self, env_name: str | None = None) -> None:
        self._focus_credentials_input(env_name)

    def _focus_command_input(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#command-input", Input).focus()

    def _focus_credentials_input(self, env_name: str | None = None) -> None:
        self._switch_view("overview")
        if not self.is_mounted:
            return
        try:
            target_env = env_name or "HIBP_API_KEY"
            target_id = f"#credential-input-{credential_slug(target_env)}"
            self.query_one(target_id, Input).focus()
        except Exception:
            return

    def _render_topbar(self) -> str:
        tor_status = "TOR" if self.session_state.execution.proxy and "socks" in self.session_state.execution.proxy else "DIRECT"
        ready = len(self.session_state.readiness.secrets_ready)
        total = ready + len(self.session_state.readiness.secrets_missing)
        db_size = _human_size(self.session_state.ops.db_path)
        return (
            f"[HANNA v3.2.0] Intelligence Control Plane | TOR={tor_status} | API keys={ready}/{total} | DB={db_size}\n"
            f"View={self.session_state.current_view} | Mode={self.session_state.execution.default_mode} | Report={self.session_state.execution.report_mode} | Runs={self.session_state.ops.runs_root}\n"
            f"Target={self.session_state.execution.target or self.session_state.target.label} | Workers={self.session_state.execution.workers} | Prompt={self.session_state.prompt_status}\n"
            f"{self._render_compact_chain_status()}"
        )

    def _render_command_board(self) -> str:
        locale = self._normalize_locale(self.session_state.locale)
        payload = COMMAND_BOARD_TRANSLATIONS[locale]
        rows = [
            f"{payload['title']} | {payload['hint']}",
            payload["subtitle"],
            f"Quick prompts: {' | '.join(payload['chips'])}",
            "",
        ]
        columns: list[str] = []
        for title, commands in payload["columns"]:
            column_lines = [title]
            column_lines.extend(commands)
            width = max(len(line) for line in column_lines)
            columns.append("\n".join(line.ljust(width) for line in column_lines))
        split_columns = [column.split("\n") for column in columns]
        max_lines = max(len(column) for column in split_columns)
        for index in range(max_lines):
            parts = []
            for column in split_columns:
                parts.append(column[index] if index < len(column) else " " * len(column[0]))
            rows.append(" | ".join(parts))
        return "\n".join(rows)

    def _render_command_status(self) -> str:
        status = self.session_state.prompt_status.upper().replace(":", " ")
        return f"[{status}]"

    def _render_startup_banner(self) -> str:
        target = self.session_state.execution.target or self.session_state.target.label
        if self.session_state.next_actions and not self.session_state.running:
            next_actions = " | ".join(self._format_next_action(action) for action in self.session_state.next_actions)
            return f"Run complete. Next: {next_actions}. Use keys or keys censys to jump to credentials. Active target: {target}"
        return f"{STARTUP_BANNER_TEXT} Active target: {target}"

    def _format_next_action(self, action: str) -> str:
        return NEXT_ACTION_LABELS.get(action, action.replace("-", " "))

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
        try:
            self.switch_screen(name)
        except KeyError:
            pass
        self._refresh_views()

    def _refresh_views(self) -> None:
        if self.is_mounted:
            self.query_one("#command-board", Static).update(self._render_command_board())
            self.query_one("#topbar", Static).update(self._render_topbar())
            self.query_one("#command-status", Static).update(self._render_command_status())
            self.query_one("#startup-banner", Static).update(self._render_startup_banner())
        self._suspend_credential_events = True
        try:
            for screen in self._screens.values():
                screen.update_state(self.session_state)
        finally:
            self._suspend_credential_events = False

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
        input_id = event.input.id or ""
        if input_id == "command-input":
            command = event.value.strip()
            event.input.value = ""
            event.input.focus()
            if not command:
                return
            append_activity(self.session_state, "info", f"$ {command}")
            self._execute_command(command)
            return
        if input_id.startswith("credential-input-"):
            slug = input_id.removeprefix("credential-input-")
            env_name = credential_env_from_slug(slug)
            if env_name:
                self._commit_credential_value(env_name, event.value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if self._suspend_credential_events:
            return
        switch_id = event.switch.id or ""
        if not switch_id.startswith("credential-toggle-"):
            return
        slug = switch_id.removeprefix("credential-toggle-")
        env_name = credential_env_from_slug(slug)
        if not env_name:
            return
        input_widget = self.query_one(f"#credential-input-{slug}", Input)
        self._set_credential_enabled(env_name, input_widget.value, event.value)

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
        normalized_command = self._route_intent(command)
        if normalized_command != command:
            append_activity(self.session_state, "info", f"intent -> {normalized_command}")
            command = normalized_command
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
        elif head in {"lang", "language", "mova", "jezyk", "kalba"} and len(tokens) > 1:
            self._set_locale(tokens[1])
        elif head == "view" and len(tokens) > 1:
            view = tokens[1].lower()
            if view in self._screens:
                self._switch_view(view)
        elif head == "focus":
            self.session_state.prompt_status = "focus-search"
            self._switch_view("overview")
            self.action_focus_command()
        elif head in {"credentials", "keys"}:
            target_env = self._resolve_credential_focus_target(tokens[1] if len(tokens) > 1 else None)
            self.session_state.prompt_status = "focus-credentials"
            self.action_focus_credentials(target_env)
            self._refresh_views()
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

    def _route_intent(self, command: str) -> str:
        raw = command.strip()
        if not raw:
            return command
        lowered = raw.lower()
        if lowered in INTENT_EXACT_COMMANDS:
            return INTENT_EXACT_COMMANDS[lowered]
        phone_target = self._extract_prefixed_value(lowered, raw, PHONE_INTENT_PREFIXES)
        if phone_target:
            return f"run --mode aggregate --target {shlex.quote(phone_target)} --modules ua_phone"
        email_target = self._extract_prefixed_value(lowered, raw, EMAIL_INTENT_PREFIXES)
        if email_target:
            return f"run --mode aggregate --target {shlex.quote(email_target)} --modules email-chain"
        username_target = self._extract_prefixed_value(lowered, raw, USERNAME_INTENT_PREFIXES)
        if username_target:
            return f"run --mode aggregate --target {shlex.quote(username_target)} --usernames {shlex.quote(username_target)}"
        if lowered.startswith("export ") or lowered.startswith("run ") or lowered.startswith("view "):
            return command
        if re.search(r"@", raw):
            return f"run --mode aggregate --target {shlex.quote(raw)} --modules email-chain"
        if re.search(r"\+?\d{7,}", raw):
            return f"run --mode aggregate --target {shlex.quote(raw)} --modules ua_phone"
        return command

    def _extract_prefixed_value(self, lowered: str, raw: str, prefixes: tuple[str, ...]) -> str | None:
        for prefix in sorted(prefixes, key=len, reverse=True):
            if lowered.startswith(prefix):
                return raw[len(prefix):].strip(" :") or None
        return None

    def _set_locale(self, value: str) -> None:
        locale = self._normalize_locale(value)
        if locale not in SUPPORTED_LOCALES:
            append_activity(self.session_state, "warn", f"Unsupported language: {value}")
            self.session_state.prompt_status = "bad-language"
            self._refresh_views()
            return
        self.session_state.locale = locale
        append_activity(self.session_state, "ok", f"Interface language set to {locale}")
        self.session_state.prompt_status = f"lang:{locale}"
        self._refresh_views()

    def _commit_credential_value(self, env_name: str, value: str) -> None:
        entry = set_credential_value(self.session_state, env_name, value)
        if entry is None:
            return
        status = "stored" if entry.value and not entry.enabled else "active" if entry.enabled else "cleared"
        append_activity(self.session_state, "info", f"Credential {env_name} {status}")
        self.session_state.prompt_status = f"cred:{env_name.lower()}"
        self._refresh_views()

    def _set_credential_enabled(self, env_name: str, value: str, enabled: bool) -> None:
        set_credential_value(self.session_state, env_name, value)
        entry = toggle_credential_entry(self.session_state, env_name, enabled)
        if entry is None:
            return
        if enabled and not entry.enabled:
            append_activity(self.session_state, "warn", f"Credential {env_name} cannot be enabled without a value")
            self.session_state.prompt_status = "cred-missing"
            self._refresh_views()
            self.notify(f"Enter a value for {env_name} before enabling it", title="HANNA", severity="warning")
            return
        state_label = "enabled" if entry.enabled else "disabled"
        append_activity(self.session_state, "ok" if entry.enabled else "info", f"Credential {env_name} {state_label}")
        self.session_state.prompt_status = f"cred:{'on' if entry.enabled else 'off'}"
        self._refresh_views()

    def _normalize_locale(self, value: str | None) -> str:
        if not value:
            return "uk"
        return LOCALE_ALIASES.get(value.lower(), value.lower())

    def _resolve_credential_focus_target(self, token: str | None) -> str | None:
        if not token:
            return None
        lowered = token.strip().lower()
        if not lowered:
            return None
        if lowered in CREDENTIAL_FOCUS_TARGETS:
            return CREDENTIAL_FOCUS_TARGETS[lowered]
        return credential_env_from_slug(lowered.replace("_", "-"))

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
        checkpoints = [
            (5, 0, "running", "wayback archive sweep"),
            (4, 0, "done", "archive delta complete"),
            (6, 1, "running", "satellite frame correlation"),
            (4, 1, "done", "geospatial overlays matched"),
        ]
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
                self._switch_view("overview")
                return
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