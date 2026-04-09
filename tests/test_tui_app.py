from __future__ import annotations

import shlex

import pytest

from models import AdapterOutcome, RunResult
from registry import resolve_modules
from tui.app import EMAIL_INTENT_PREFIXES, INTENT_EXACT_COMMANDS, PHONE_INTENT_PREFIXES, USERNAME_INTENT_PREFIXES, HannaTUIApp
from tui.screens import OverviewScreen
from tui.state import build_default_session_state


def test_apply_event_updates_ui_state_transitions(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    app._apply_event({"type": "run_started", "mode": "chain"})
    app._apply_event({"type": "phase", "phase": "ingest", "detail": "ingesting metadata"})
    app._apply_event({"type": "phase_counters", "phase": "ingest", "counters": {"total_files": 2, "ingested": 1}})
    app._apply_event({"type": "module", "module": "httpx_probe", "status": "running", "detail": "worker started"})
    app._apply_event({"type": "activity", "level": "info", "text": "Scheduler active"})

    result = RunResult(
        target_name="Case Entity",
        mode="chain",
        modules_run=["httpx_probe"],
        outcomes=[AdapterOutcome(module_name="httpx_probe", lane="fast")],
        started_at="2026-04-08T01:00:00",
        finished_at="2026-04-08T01:00:05",
        extra={"ingestion": {"ingested": 1, "rejected": 1, "skipped": 0}, "clusters": 2},
    )
    app._apply_event({"type": "run_finished", "result": result})

    assert app.session_state.running is False
    assert app.session_state.pipeline.phase == "completed"
    assert app.session_state.prompt_status == "review-ready"
    assert app.session_state.current_view == "overview"
    assert app.session_state.next_actions == ["review", "print", "diagnostics", "new-search", "export-stix", "export-zip"]
    assert "ingest" in app.session_state.pipeline.phase_counters
    assert app.session_state.pipeline.phase_timeline
    assert any(item.level == "info" and item.text == "Scheduler active" for item in app.session_state.activity)
    assert "Chain:" in app._render_topbar()


def test_startup_banner_shows_next_actions_after_run():
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    app.session_state.next_actions = ["review", "print", "diagnostics"]
    app.session_state.latest_result = RunResult(
        target_name="Case Entity",
        mode="aggregate",
        started_at="2026-04-08T01:00:00",
        finished_at="2026-04-08T01:00:05",
    )

    banner = app._render_startup_banner()

    assert "Run complete. Next:" in banner
    assert "review | print | diagnostics" in banner


def test_render_compact_chain_status_includes_recent_counters():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)
    total_modules = len(app.session_state.pipeline.modules)

    app.session_state.pipeline.phase_counters["ingest"] = "total_files=2, ingested=1"
    app.session_state.pipeline.phase_counters["resolve"] = "clusters=3"
    app.session_state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] resolve: clusters=3")
    app.session_state.pipeline.phase = "resolve"
    app.session_state.pipeline.modules[0].status = "running"

    rendered = app._render_compact_chain_status()

    assert "phase=resolve" in rendered
    assert f"modules done=0/{total_modules} run=1 queue=0 err=0" in rendered
    assert "ingest[total_files=2, ingested=1]" in rendered
    assert "resolve[clusters=3]" in rendered


def test_render_compact_chain_status_shows_module_summary_when_idle():
    state = build_default_session_state(target="Case Entity", modules=["pd-infra", "shodan"], default_mode="chain")
    app = HannaTUIApp(session_state=state)
    total_modules = len(app.session_state.pipeline.modules)

    app.session_state.pipeline.phase = "idle"
    app.session_state.pipeline.modules[0].status = "done"
    app.session_state.pipeline.modules[1].status = "error"

    rendered = app._render_compact_chain_status()

    assert rendered == f"Chain: phase=idle | modules done=1/{total_modules} run=0 queue=0 err=1"


def test_action_clear_timeline_resets_pipeline_history(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    app.session_state.pipeline.phase = "deep_recon"
    app.session_state.pipeline.phase_counters["ingest"] = "total_files=2"
    app.session_state.pipeline.phase_timeline.append("[2026-04-08T01:00:00] ingest: total_files=2")
    app.session_state.last_result_summary = ["summary"]

    app.action_clear_timeline()

    assert app.session_state.pipeline.phase == "idle"
    assert app.session_state.pipeline.phase_counters == {}
    assert app.session_state.pipeline.phase_timeline == []
    assert app.session_state.last_result_summary == []


def test_session_screen_update_state_before_mount_does_not_crash():
    screen = OverviewScreen()
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")

    screen.update_state(state)

    assert screen.session_state is state


def test_action_toggle_rejected_flips_visibility_flag(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="chain")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    assert app.session_state.show_rejected is False
    app.action_toggle_rejected()
    assert app.session_state.show_rejected is True


def test_command_prompt_run_updates_profile_and_starts_mode(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="idle")
    app = HannaTUIApp(session_state=state)
    started: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_start_run", lambda mode: started.append(mode))

    app._execute_command("run --mode full-spectrum --target 'Ivan Signal' --usernames ivan_ops")

    assert started == ["aggregate"]
    assert app.session_state.execution.target == "Ivan Signal"
    assert "ivan_ops" in app.session_state.execution.known_usernames


def test_language_command_switches_locale(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)

    app._execute_command("lang en")

    assert app.session_state.locale == "en"
    assert app.session_state.prompt_status == "lang:en"


def test_credential_helpers_update_session_state(monkeypatch):
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "notify", lambda *args, **kwargs: None)

    app._commit_credential_value("SHODAN_API_KEY", "temporary-shodan-key")
    entry = next(item for item in app.session_state.credentials if item.env_name == "SHODAN_API_KEY")
    assert entry.value == "temporary-shodan-key"
    assert entry.enabled is False

    app._set_credential_enabled("SHODAN_API_KEY", "temporary-shodan-key", True)
    assert entry.enabled is True

    app._set_credential_enabled("SHODAN_API_KEY", "temporary-shodan-key", False)
    assert entry.enabled is False


def test_render_command_board_uses_selected_locale():
    state = build_default_session_state(target="Case Entity", locale="pl")
    app = HannaTUIApp(session_state=state)

    rendered = app._render_command_board()

    assert "CENTRUM KOMEND" in rendered
    assert "Pisz naturalnie" in rendered
    assert "Quick prompts:" in rendered


def test_intent_router_maps_ukrainian_phone_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="idle")
    app = HannaTUIApp(session_state=state)
    started: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_start_run", lambda mode: started.append(mode))

    app._execute_command("знайди по номеру +380991234598")

    assert started == ["aggregate"]
    assert app.session_state.execution.target == "+380991234598"
    assert app.session_state.execution.resolved_modules == ["ua_phone"]


def test_intent_router_maps_english_email_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity", modules=["pd-infra"], default_mode="idle")
    app = HannaTUIApp(session_state=state)
    started: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_start_run", lambda mode: started.append(mode))

    app._execute_command("check email case@example.com")

    assert started == ["aggregate"]
    assert app.session_state.execution.target == "case@example.com"
    assert app.session_state.execution.resolved_modules == resolve_modules(["email-chain"])


def test_intent_router_maps_navigation_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_switch_view", lambda name: setattr(app.session_state, "current_view", name))

    app._execute_command("show diagnostics")

    assert app.session_state.current_view == "readiness"


def test_intent_router_maps_focus_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    focused: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_switch_view", lambda name: setattr(app.session_state, "current_view", name))
    monkeypatch.setattr(app, "action_focus_command", lambda: focused.append("focus"))

    app._execute_command("new search")

    assert app.session_state.current_view == "overview"
    assert app.session_state.prompt_status == "focus-search"
    assert focused == ["focus"]


def test_intent_router_maps_keys_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    focused: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "action_focus_credentials", lambda env_name=None: focused.append(env_name or "credentials"))

    app._execute_command("keys")

    assert app.session_state.prompt_status == "focus-credentials"
    assert focused == ["credentials"]


def test_intent_router_maps_keys_service_phrase(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    focused: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "action_focus_credentials", lambda env_name=None: focused.append(env_name))

    app._execute_command("keys censys")

    assert app.session_state.prompt_status == "focus-credentials"
    assert focused == ["CENSYS_API_ID"]


def test_intent_router_maps_print_to_export(monkeypatch):
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    exported: list[str] = []

    monkeypatch.setattr(app, "_refresh_views", lambda: None)
    monkeypatch.setattr(app, "_export_last_result", lambda artifact: exported.append(artifact))

    app._execute_command("print")

    assert exported == ["zip"]


def test_startup_banner_mentions_keys_navigation_after_run():
    state = build_default_session_state(target="Case Entity")
    app = HannaTUIApp(session_state=state)
    app.session_state.next_actions = ["review", "print", "diagnostics"]

    banner = app._render_startup_banner()

    assert "Use keys or keys censys" in banner


@pytest.mark.parametrize(("phrase", "expected"), sorted(INTENT_EXACT_COMMANDS.items()))
def test_route_intent_covers_all_exact_phrase_aliases(phrase, expected):
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))

    assert app._route_intent(phrase) == expected


@pytest.mark.parametrize("prefix", PHONE_INTENT_PREFIXES)
def test_route_intent_covers_all_phone_prefixes(prefix):
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))
    target = "+380991234598"

    expected = f"run --mode aggregate --target {shlex.quote(target)} --modules ua_phone"

    assert app._route_intent(f"{prefix} {target}") == expected


@pytest.mark.parametrize("prefix", EMAIL_INTENT_PREFIXES)
def test_route_intent_covers_all_email_prefixes(prefix):
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))
    target = "case@example.com"

    expected = f"run --mode aggregate --target {shlex.quote(target)} --modules email-chain"

    assert app._route_intent(f"{prefix} {target}") == expected


@pytest.mark.parametrize("prefix", USERNAME_INTENT_PREFIXES)
def test_route_intent_covers_all_username_prefixes(prefix):
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))
    target = "caseuser"

    expected = f"run --mode aggregate --target {shlex.quote(target)} --usernames {shlex.quote(target)}"

    assert app._route_intent(f"{prefix} {target}") == expected


def test_route_intent_falls_back_for_raw_email():
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))
    target = "raw@example.com"

    expected = f"run --mode aggregate --target {shlex.quote(target)} --modules email-chain"

    assert app._route_intent(target) == expected


def test_route_intent_falls_back_for_raw_phone():
    app = HannaTUIApp(session_state=build_default_session_state(target="Case Entity"))
    target = "+380501112233"

    expected = f"run --mode aggregate --target {shlex.quote(target)} --modules ua_phone"

    assert app._route_intent(target) == expected