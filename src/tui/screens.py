from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static, Switch

from smart_summary import summarize_text
from tui.state import CREDENTIAL_SPECS, ExecutionConfig, SessionState, TargetState, credential_slug


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

OVERVIEW_TEXT = {
    "uk": {
        "finding": "ГОЛОВНИЙ РЕЗУЛЬТАТ",
        "finding_empty": "Ще немає результату. Почніть з phone, email або username у головному рядку пошуку.",
        "signals": "КЛЮЧОВІ СИГНАЛИ",
        "actions": "НАСТУПНІ ДІЇ",
        "actions_empty": "Після запуску тут з'являться review, print, diagnostics, new search та явний export.",
        "digest": "ЩО ПЕРЕВІРЕНО",
        "manual_exports": "Експорт тепер лише явною дією.",
    },
    "en": {
        "finding": "MAIN FINDING",
        "finding_empty": "No result yet. Start with phone, email, or username in the main search bar.",
        "signals": "KEY SIGNALS",
        "actions": "NEXT ACTIONS",
        "actions_empty": "After a run you will see review, print, diagnostics, new search, and explicit export choices here.",
        "digest": "RUN DIGEST",
        "manual_exports": "Exports are manual actions now.",
    },
    "pl": {
        "finding": "GLOWNY WYNIK",
        "finding_empty": "Jeszcze nie ma wyniku. Zacznij od phone, email lub username w glownym pasku wyszukiwania.",
        "signals": "KLUCZOWE SYGNALY",
        "actions": "NASTEPNY KROK",
        "actions_empty": "Po uruchomieniu zobaczysz tutaj review, print, diagnostics, new search oraz jawny export.",
        "digest": "PODSUMOWANIE RUN",
        "manual_exports": "Eksport jest teraz tylko jawna akcja.",
    },
    "lt": {
        "finding": "PAGRINDINIS REZULTATAS",
        "finding_empty": "Rezultato dar nera. Pradekite nuo phone, email arba username pagrindineje paieskoje.",
        "signals": "PAGRINDINIAI SIGNALAI",
        "actions": "KITI VEIKSMAI",
        "actions_empty": "Po paleidimo cia matysite review, print, diagnostics, new search ir aisku export pasirinkima.",
        "digest": "RUN SANTRAUKA",
        "manual_exports": "Eksportas dabar tik aiskus veiksmas.",
    },
}

DIAGNOSTICS_TEXT = {
    "uk": {
        "pipeline_title": "[Pipeline // Live Ops]",
        "pipeline_phase_counters": "ЛІЧИЛЬНИКИ ФАЗ",
        "pipeline_module_grid": "СІТКА МОДУЛІВ",
        "pipeline_recent_timeline": "ОСТАННЯ ХРОНОЛОГІЯ",
        "pipeline_result_digest": "ПІДСУМОК РЕЗУЛЬТАТУ",
        "pipeline_none": "none",
        "readiness_title": "[Readiness // Gate]",
        "readiness_secrets": "СЕКРЕТИ",
        "readiness_check_matrix": "МАТРИЦЯ ПЕРЕВІРОК",
        "activity_title": "[Activity // Live Console]",
        "activity_summary": "ПІДСУМОК ПОТОКУ",
        "activity_recent": "ОСТАННІ ПОДІЇ",
        "activity_none": "ще немає подій",
    },
    "en": {
        "pipeline_title": "[Pipeline // Live Ops]",
        "pipeline_phase_counters": "PHASE COUNTERS",
        "pipeline_module_grid": "MODULE GRID",
        "pipeline_recent_timeline": "RECENT TIMELINE",
        "pipeline_result_digest": "RESULT DIGEST",
        "pipeline_none": "none",
        "readiness_title": "[Readiness // Gate]",
        "readiness_secrets": "SECRETS",
        "readiness_check_matrix": "CHECK MATRIX",
        "activity_title": "[Activity // Live Console]",
        "activity_summary": "STREAM SUMMARY",
        "activity_recent": "RECENT EVENTS",
        "activity_none": "no events yet",
    },
    "pl": {
        "pipeline_title": "[Pipeline // Live Ops]",
        "pipeline_phase_counters": "LICZNIKI FAZ",
        "pipeline_module_grid": "SIATKA MODULOW",
        "pipeline_recent_timeline": "OSTATNIA CHRONOLOGIA",
        "pipeline_result_digest": "SKROT WYNIKU",
        "pipeline_none": "none",
        "readiness_title": "[Readiness // Gate]",
        "readiness_secrets": "SEKRETY",
        "readiness_check_matrix": "MACIERZ KONTROLI",
        "activity_title": "[Activity // Live Console]",
        "activity_summary": "PODSUMOWANIE STRUMIENIA",
        "activity_recent": "OSTATNIE ZDARZENIA",
        "activity_none": "brak zdarzen",
    },
    "lt": {
        "pipeline_title": "[Pipeline // Live Ops]",
        "pipeline_phase_counters": "FAZIU SKAITIKLIAI",
        "pipeline_module_grid": "MODULIU TINKLAS",
        "pipeline_recent_timeline": "NAUJAUSIA CHRONOLOGIJA",
        "pipeline_result_digest": "REZULTATO SANTRAUKA",
        "pipeline_none": "none",
        "readiness_title": "[Readiness // Gate]",
        "readiness_secrets": "SLAPTOS REIKSMES",
        "readiness_check_matrix": "PATIKRU MATRICA",
        "activity_title": "[Activity // Live Console]",
        "activity_summary": "SRAUTO SANTRAUKA",
        "activity_recent": "NAUJAUSI IVYKIAI",
        "activity_none": "ivykiu dar nera",
    },
}

CREDENTIALS_TEXT = {
    "uk": {
        "title": "КЛЮЧІ ТА ДОСТУП",
        "hint": "Session-only. Значення не пишуться у файли; Enter застосовує, switch вмикає або відсікає env.",
        "columns": "СЕРВІС        МОДУЛЬ       СТАН",
        "active": "active",
        "stored": "stored",
        "missing": "missing",
        "off": "off",
    },
    "en": {
        "title": "KEY CONTROL",
        "hint": "Session-only. Values are not written to disk; press Enter to apply, use the switch to expose or cut env.",
        "columns": "SERVICE       MODULE       STATE",
        "active": "active",
        "stored": "stored",
        "missing": "missing",
        "off": "off",
    },
    "pl": {
        "title": "KLUCZE I DOSTEP",
        "hint": "Tylko sesja. Wartosci nie sa zapisywane na dysk; Enter zapisuje, przelacznik wlacza lub odcina env.",
        "columns": "SERWIS        MODUL        STAN",
        "active": "active",
        "stored": "stored",
        "missing": "missing",
        "off": "off",
    },
    "lt": {
        "title": "RAKTAI IR PRIEIGA",
        "hint": "Tik sesijai. Reiksmes neirasomos i diska; Enter pritaiko, jungiklis ijungia arba atjungia env.",
        "columns": "SERVISAS      MODULIS      BUSENA",
        "active": "active",
        "stored": "stored",
        "missing": "missing",
        "off": "off",
    },
}


class AsciiHeader(Static):
    def render_header(self, session_state: SessionState) -> None:
        ready = len(session_state.readiness.secrets_ready)
        total = ready + len(session_state.readiness.secrets_missing)
        time_label = session_state.started_at.replace("T", " ")[:16]
        tor_status = "TOR ROUTED" if session_state.execution.proxy and "socks" in (session_state.execution.proxy or "") else "DIRECT PATH"
        self.update(
            f"[bold #00ffcc]{ASCII_HANNA}[/]   [bold #19f9ff]HANNA v3.2.0[/] [bold #ff44aa]INTELLIGENCE CONTROL PLANE[/]\n"
            f"[#7fdbff]{time_label}[/] | [#ffcc00]{tor_status}[/] | [#ff6bdf]mode={session_state.execution.default_mode}[/] | [#00ff88]phase={session_state.pipeline.phase}[/]\n"
            f"[#19f9ff]api keys={ready}/{total}[/] | [#ff9f6b]warnings={session_state.readiness.warnings}[/] | [#ff4466]failures={session_state.readiness.hard_failures}[/] | [#c89bff]prompt={session_state.prompt_status}[/]"
        )


class MainFindingPanel(Static):
    def render_main(self, session_state: SessionState, summary_text: str, risk_tags: list[str]) -> None:
        text = _overview_text(session_state, "finding")
        result = session_state.latest_result
        lines = [text]
        if result is None:
            lines.extend([
                _overview_text(session_state, "finding_empty"),
                "",
                "Try: phone +380...",
                "Try: email name@example.com",
                "Try: username handle",
            ])
            self.update("\n".join(lines))
            return
        best_signal = _best_result_signal(result)
        lines.append(_build_result_headline(result))
        lines.extend(_take_lines(summary_text, 4))
        lines.append("")
        if best_signal:
            lines.append(f"Top signal: {best_signal.observable_type} {_shorten(best_signal.value, 42)} ({best_signal.confidence:.0%})")
        lines.append(
            f"Cross-confirmed={len(result.cross_confirmed)} | errors={result.error_count} | mode={result.mode}"
        )
        if risk_tags:
            lines.append(f"Flags: {' '.join(risk_tags)}")
        self.update("\n".join(lines))


class EvidenceStripPanel(Static):
    def render_evidence(self, session_state: SessionState) -> None:
        confirmed = sum(1 for item in session_state.observables if item.status == "confirmed")
        candidates = sum(1 for item in session_state.observables if item.status == "candidate")
        hidden = sum(1 for item in session_state.observables if item.status == "rejected")
        phones = ", ".join(_top_observable_values(session_state, "phone")) or "none"
        emails = ", ".join(_top_observable_values(session_state, "email")) or "none"
        usernames = ", ".join(_top_observable_values(session_state, "username")) or "none"
        lines = [
            _overview_text(session_state, "signals"),
            f"confirmed={confirmed} | candidate={candidates} | hidden_noise={hidden}",
            "",
            f"Phones    : {_shorten(phones, 60)}",
            f"Emails    : {_shorten(emails, 60)}",
            f"Usernames : {_shorten(usernames, 60)}",
        ]
        self.update("\n".join(lines))


class NextActionsPanel(Static):
    def render_actions(self, session_state: SessionState) -> None:
        lines = [_overview_text(session_state, "actions")]
        if not session_state.next_actions:
            lines.extend([
                _overview_text(session_state, "actions_empty"),
                "",
                "review | print | diagnostics | new search",
            ])
            self.update("\n".join(lines))
            return
        for action in session_state.next_actions:
            lines.append(f"- {_format_action_command(action)}")
        self.update("\n".join(lines))


class CredentialControlPanel(Static):
    def compose(self) -> ComposeResult:
        yield Static(id="credentials-title")
        yield Static(id="credentials-hint")
        yield Static(id="credentials-columns")
        for env_name, label, module in CREDENTIAL_SPECS:
            slug = credential_slug(env_name)
            with Horizontal(classes="credential-row", id=f"credential-row-{slug}"):
                yield Static(label, classes="credential-label")
                yield Static(module, classes="credential-module")
                yield Input(placeholder=env_name, password=True, id=f"credential-input-{slug}", classes="credential-input")
                yield Switch(value=False, id=f"credential-toggle-{slug}", classes="credential-toggle")
                yield Static("off", id=f"credential-state-{slug}", classes="credential-state")

    def render_credentials(self, session_state: SessionState) -> None:
        self.query_one("#credentials-title", Static).update(_credential_text(session_state, "title"))
        self.query_one("#credentials-hint", Static).update(_credential_text(session_state, "hint"))
        self.query_one("#credentials-columns", Static).update(_credential_text(session_state, "columns"))
        for entry in session_state.credentials:
            slug = credential_slug(entry.env_name)
            input_widget = self.query_one(f"#credential-input-{slug}", Input)
            toggle_widget = self.query_one(f"#credential-toggle-{slug}", Switch)
            state_widget = self.query_one(f"#credential-state-{slug}", Static)
            if input_widget.value != entry.value:
                input_widget.value = entry.value
            if toggle_widget.value != entry.enabled:
                toggle_widget.value = entry.enabled
            state_widget.update(_credential_state_label(session_state, entry.enabled, bool(entry.value)))


class RunDigestPanel(Static):
    def render_digest(self, session_state: SessionState) -> None:
        lines = [_overview_text(session_state, "digest")]
        result = session_state.latest_result
        if result is None:
            lines.extend([
                "No run completed in this session.",
                "",
                _overview_text(session_state, "manual_exports"),
            ])
            self.update("\n".join(lines))
            return
        runtime = result.runtime_summary()
        modules = ", ".join(result.modules_run[:4]) or "none"
        if len(result.modules_run) > 4:
            modules = f"{modules}, +{len(result.modules_run) - 4} more"
        lines.extend([
            f"Modules checked: {modules}",
            f"Queued={runtime['queued']} | completed={runtime['completed']} | failed={runtime['failed']} | timed_out={runtime['timed_out']}",
            f"New phones={len(result.new_phones)} | new emails={len(result.new_emails)} | total hits={result.total_hits}",
            _overview_text(session_state, "manual_exports"),
        ])
        if isinstance(result.extra, dict) and result.extra.get("output_path"):
            lines.append(f"Report: {_shorten(str(result.extra['output_path']), 58)}")
        if result.errors:
            first_error = result.errors[0]
            lines.append(f"First issue: {_shorten(first_error.get('error', ''), 58)}")
        self.update("\n".join(lines))


class TargetDossierPanel(Static):
    def render_target(self, session_state: SessionState) -> None:
        target = session_state.target
        execution = session_state.execution
        primary_username = (target.usernames or execution.known_usernames or ["none"])[0]
        primary_phone = (target.phones or execution.known_phones or ["none"])[0]
        primary_email = (target.emails or [_infer_email_hint(target.label)])[0]
        domain = _infer_primary_domain(target, execution)
        lines = [
            "ACTIVE TARGETS & INPUT",
            "     .-''''-.",
            "   .'  .--.  '.",
            "  /   /    \\   \\",
            "  |   | () |   |",
            "  |   | /\\ |   |",
            "  \\   \\__/   /",
            "   '.      .'",
            "     '-..-'",
            "",
            "Active seed:",
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
    def render_meter(self, score: float, level: str, risk_count: int, tags: list[str] | None = None) -> None:
        clamped = max(0, min(100, int(score)))
        rows = ["THREAT LEVEL // SECURITY SCORE"]
        rows.extend(_semi_gauge(clamped))
        rows.extend(
            [
                f"score {clamped:03d}",
                f"lvl   {level.upper()[:4]}",
                f"flags {risk_count:02d}",
                " ".join(tags or _default_risk_tags(level, risk_count)),
            ]
        )
        self.update("\n".join(rows))


class LaneContainer(Static):
    def render_lane(self, title: str, modules: list[tuple[str, str, str]], confirmed: int, pending: int, rejected: int, *, slow: bool = False) -> None:
        lines = [
            f"[bold #ffcc00][ {title} ][/]",
            f"SNR [bold #00ff88]{confirmed} confirmed[/] | [bold #ffcc00]{pending} pending[/] | [bold #ff4466]{rejected} noise[/]",
        ]
        if not modules:
            lines.append("  no modules assigned")
        for name, status, detail in modules[:8]:
            meter = _slow_lane_meter(status) if slow else _module_meter(status)
            lines.append(f"  {_spinner(status)} {name:<16} {_status_label(status):<10} {meter} {_shorten(detail, 24)}")
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
        self.update(f"SMART AI SUMMARY\n{summary_text}\n\nThreat tags: {tags}")


class ObservablesPanel(Static):
    def render_observables(self, session_state: SessionState) -> None:
        visible = [item for item in session_state.observables if session_state.show_rejected or item.status != "rejected"]
        hidden_count = sum(1 for item in session_state.observables if item.status == "rejected") if not session_state.show_rejected else 0
        lines = [
            "ENTITY GRAPH / OBSERVABLES",
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
            f"{'▸' if not session_state.show_rejected else '▾'} Rejected / low confidence hidden: {hidden_count} | press v to toggle noise rows",
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
            "GLOBAL STATUS",
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
            "COMMAND DECK\n"
            "phone +380... | email name@example.com\n"
            "username handle | review | diagnostics\n"
            "activity | pipeline | print\n"
            "export stix | export zip | keys\n"
            "lang uk|en|pl|lt | / focus | q quit"
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
    #main-finding,
    #evidence-strip,
    #next-actions,
    #credentials-panel,
    #run-digest,
    #pipeline-monitor,
    #observables-panel,
    #activity-feed {
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

    #center-column {
        width: 1fr;
        padding-right: 1;
    }

    #right-column {
        width: 58;
    }

    #main-finding,
    #evidence-strip,
    #next-actions,
    #credentials-panel,
    #run-digest,
    #pipeline-monitor,
    #observables-panel,
    #activity-feed {
        margin-bottom: 1;
    }

    #pipeline-monitor {
        height: 10;
        border: round #ff44aa;
        background: #120812;
    }

    #main-finding {
        height: 12;
        border: round #c89bff;
        background: #0e0819;
    }

    #evidence-strip {
        height: 8;
        border: round #7fdbff;
        background: #0c0a18;
    }

    #next-actions {
        height: 10;
        border: round #ffcc00;
        background: #0e0b14;
        color: #ffcc00;
    }

    #credentials-panel {
        height: 18;
        border: round #20d5ff;
        background: #081018;
    }

    .credential-row {
        height: 3;
        align: left middle;
    }

    .credential-label {
        width: 14;
        color: #7fdbff;
    }

    .credential-module {
        width: 11;
        color: #c89bff;
    }

    .credential-input {
        width: 1fr;
        margin-right: 1;
        background: #040912;
        color: #f2f1f5;
        border: round #19f9ff;
    }

    .credential-toggle {
        width: 8;
        margin-right: 1;
    }

    .credential-state {
        width: 8;
        color: #00ff88;
    }

    #run-digest {
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

    """

    def __init__(self) -> None:
        super().__init__(name="overview", title="Overview")

    def compose(self) -> ComposeResult:
        with Vertical(id="overview-root"):
            yield AsciiHeader(id="ascii-header")
            with Horizontal(id="overview-grid"):
                with Vertical(id="center-column"):
                    yield MainFindingPanel(id="main-finding")
                    yield EvidenceStripPanel(id="evidence-strip")
                    yield ObservablesPanel(id="observables-panel")
                with Vertical(id="right-column"):
                    yield NextActionsPanel(id="next-actions")
                    yield CredentialControlPanel(id="credentials-panel")
                    yield RunDigestPanel(id="run-digest")
                    yield ActivityFeedPanel(id="activity-feed")
            yield PipelineMonitorPanel(id="pipeline-monitor")

    def refresh_screen(self) -> None:
        if not self.session_state:
            return
        target = self.session_state.target
        ai_input = _build_summary_input(self.session_state)
        smart = summarize_text(target.label or "No target selected", ai_input or "No active intelligence yet.")
        risk_tags = [f"[{flag.code.upper()}]" for flag in smart.risk_flags[:3]]

        self.query_one("#ascii-header", AsciiHeader).render_header(self.session_state)
        self.query_one("#main-finding", MainFindingPanel).render_main(self.session_state, smart.summary, risk_tags)
        self.query_one("#evidence-strip", EvidenceStripPanel).render_evidence(self.session_state)
        self.query_one("#next-actions", NextActionsPanel).render_actions(self.session_state)
        self.query_one("#credentials-panel", CredentialControlPanel).render_credentials(self.session_state)
        self.query_one("#run-digest", RunDigestPanel).render_digest(self.session_state)
        self.query_one("#pipeline-monitor", PipelineMonitorPanel).render_pipeline(self.session_state)
        self.query_one("#observables-panel", ObservablesPanel).render_observables(self.session_state)
        self.query_one("#activity-feed", ActivityFeedPanel).render_activity(self.session_state)


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
        self.query_one("#pipeline-body", Static).update(_build_pipeline_body(self.session_state))


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
        self.query_one("#readiness-body", Static).update(_build_readiness_body(self.session_state))


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
        self.query_one("#activity-body", Static).update(_build_activity_body(self.session_state))


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


def _overview_text(session_state: SessionState, key: str) -> str:
    locale = session_state.locale if session_state.locale in OVERVIEW_TEXT else "en"
    return OVERVIEW_TEXT[locale][key]


def _diagnostics_text(session_state: SessionState, key: str) -> str:
    locale = session_state.locale if session_state.locale in DIAGNOSTICS_TEXT else "en"
    return DIAGNOSTICS_TEXT[locale][key]


def _credential_text(session_state: SessionState, key: str) -> str:
    locale = session_state.locale if session_state.locale in CREDENTIALS_TEXT else "en"
    return CREDENTIALS_TEXT[locale][key]


def _credential_state_label(session_state: SessionState, enabled: bool, has_value: bool) -> str:
    if enabled and has_value:
        return _credential_text(session_state, "active")
    if has_value:
        return _credential_text(session_state, "stored")
    if enabled:
        return _credential_text(session_state, "missing")
    return _credential_text(session_state, "off")


def _build_result_headline(result: RunResult) -> str:
    if result.total_hits:
        return f"{result.total_hits} finding(s) across {len(result.modules_run)} module(s) for {result.target_name}"
    if result.error_count:
        return f"Run completed with {result.error_count} issue(s) and no confirmed findings yet"
    return f"Run completed for {result.target_name} with no new findings yet"


def _best_result_signal(result: RunResult):
    if not result.all_hits:
        return None
    return max(result.all_hits, key=lambda hit: (hit.confidence, hit.observable_type, hit.value))


def _take_lines(value: str, limit: int) -> list[str]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[:limit]


def _top_observable_values(session_state: SessionState, kind: str) -> list[str]:
    values = [item.value for item in session_state.observables if item.kind == kind and item.status != "rejected"]
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered[:3]


def _format_action_command(action: str) -> str:
    mapping = {
        "review": "review",
        "print": "print",
        "diagnostics": "diagnostics",
        "new-search": "new search",
        "export-stix": "export stix",
        "export-zip": "export zip",
    }
    return mapping.get(action, action.replace("-", " "))


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


def _build_pipeline_body(session_state: SessionState) -> str:
    modules = session_state.pipeline.modules
    total = len(modules)
    done = sum(1 for module in modules if module.status == "done")
    running = sum(1 for module in modules if module.status == "running")
    queued = sum(1 for module in modules if module.status in {"queued", "idle"})
    errors = sum(1 for module in modules if module.status in {"error", "timeout"})
    next_actions = ", ".join(_format_action_command(action) for action in session_state.next_actions[:4]) or "none"
    lines = [
        _diagnostics_text(session_state, "pipeline_title"),
        f"phase={session_state.pipeline.phase} | done={done}/{total} | run={running} | queue={queued} | err={errors}",
        f"progress={session_state.pipeline.progress_label}",
        f"next={next_actions}",
        "",
        _diagnostics_text(session_state, "pipeline_phase_counters"),
    ]
    if session_state.pipeline.phase_counters:
        for phase_name, detail in session_state.pipeline.phase_counters.items():
            lines.append(f"  {phase_name:<16} {detail}")
    else:
        lines.append(f"  {_diagnostics_text(session_state, 'pipeline_none')}")
    lines.extend(["", _diagnostics_text(session_state, "pipeline_module_grid")])
    if modules:
        for module in modules[:12]:
            lines.append(
                f"  {_module_state_glyph(module.status)} {module.name:<16} {module.lane:<4} {_status_label(module.status):<8} {_shorten(module.detail, 48)}"
            )
    else:
        lines.append(f"  {_diagnostics_text(session_state, 'pipeline_none')}")
    lines.extend(["", _diagnostics_text(session_state, "pipeline_recent_timeline")])
    if session_state.pipeline.phase_timeline:
        lines.extend(f"  {item}" for item in session_state.pipeline.phase_timeline[-6:])
    else:
        lines.append(f"  {_diagnostics_text(session_state, 'pipeline_none')}")
    if session_state.last_result_summary:
        lines.extend(["", _diagnostics_text(session_state, "pipeline_result_digest")])
        lines.extend(f"  {line}" for line in session_state.last_result_summary[:6])
    return "\n".join(lines)


def _build_readiness_body(session_state: SessionState) -> str:
    readiness = session_state.readiness
    checks = readiness.checks
    total_secrets = len(readiness.secrets_ready) + len(readiness.secrets_missing)
    proxy_label = session_state.execution.proxy or "direct"
    lines = [
        _diagnostics_text(session_state, "readiness_title"),
        f"fail={readiness.hard_failures} | warn={readiness.warnings} | keys_ready={len(readiness.secrets_ready)}/{total_secrets}",
        f"mode={session_state.execution.default_mode} | proxy={proxy_label} | no_preflight={_bool_text(session_state.execution.no_preflight)}",
        "",
        _diagnostics_text(session_state, "readiness_secrets"),
        f"  ready   : {', '.join(readiness.secrets_ready) or 'none'}",
        f"  missing : {', '.join(readiness.secrets_missing) or 'none'}",
        "",
        _diagnostics_text(session_state, "readiness_check_matrix"),
    ]
    if checks:
        for check in checks:
            lines.append(f"  {_preflight_glyph(check.status)} {check.name:<22} {check.status.upper():<5} {_shorten(check.detail, 54)}")
    else:
        lines.append(f"  {_diagnostics_text(session_state, 'pipeline_none')}")
    return "\n".join(lines)


def _build_activity_body(session_state: SessionState) -> str:
    events = session_state.activity[-24:]
    info_count = sum(1 for item in events if item.level == "info")
    ok_count = sum(1 for item in events if item.level == "ok")
    warn_count = sum(1 for item in events if item.level == "warn")
    error_count = sum(1 for item in events if item.level == "error")
    phase = session_state.pipeline.phase
    running = "yes" if session_state.running else "no"
    lines = [
        _diagnostics_text(session_state, "activity_title"),
        f"phase={phase} | running={running} | prompt={session_state.prompt_status}",
        f"events={len(events)} | info={info_count} | ok={ok_count} | warn={warn_count} | error={error_count}",
        "",
        _diagnostics_text(session_state, "activity_summary"),
        f"target={_shorten(session_state.execution.target or session_state.target.label, 42)} | next={', '.join(_format_action_command(action) for action in session_state.next_actions[:3]) or 'none'}",
        "",
        _diagnostics_text(session_state, "activity_recent"),
    ]
    if events:
        for item in events:
            lines.append(
                f"  {_level_console_glyph(item.level)} {item.timestamp[11:19]} {_level_badge(item.level):<6} {_shorten(item.text, 76)}"
            )
    else:
        lines.append(f"  {_diagnostics_text(session_state, 'activity_none')}")
    return "\n".join(lines)


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


def _level_console_glyph(level: str) -> str:
    glyphs = {
        "info": ">",
        "ok": "+",
        "warn": "!",
        "error": "x",
    }
    return glyphs.get(level, ">")


def _module_state_glyph(status: str) -> str:
    glyphs = {
        "done": "+",
        "running": ">",
        "queued": "~",
        "idle": ".",
        "error": "!",
        "timeout": "x",
    }
    return glyphs.get(status, ".")


def _preflight_glyph(status: str) -> str:
    glyphs = {
        "ok": "+",
        "warn": "!",
        "fail": "x",
    }
    return glyphs.get(status, ".")


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


def _slow_lane_meter(status: str) -> str:
    meters = {
        "done": "██████",
        "running": "███░░░",
        "queued": "█░░░░░",
        "idle": "░░░░░░",
        "error": "!!░░░░",
        "timeout": "xx░░░░",
    }
    return meters.get(status, "░░░░░░")


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


def _default_risk_tags(level: str, risk_count: int) -> list[str]:
    if level == "high":
        return ["[ALERT]", f"[RISK {risk_count:02d}]", "[INFO]"]
    if level == "medium":
        return ["[WATCH]", f"[RISK {risk_count:02d}]", "[INFO]"]
    return ["[INFO]", f"[FLAGS {risk_count:02d}]"]


def _semi_gauge(score: int) -> list[str]:
    width = 12
    fill = max(0, min(width, round((score / 100) * width)))
    arc = "█" * fill + "·" * (width - fill)
    return [
        "   ╭────────────╮",
        f"  ╱ {arc[:6]} {arc[6:]} ╲",
        f" ╱      {score:03d}      ╲",
        "╰────────────────╯",
    ]


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