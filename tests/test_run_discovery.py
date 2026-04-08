from __future__ import annotations

import run_discovery


def test_run_discovery_list_modules_exits_after_printing_inventory(capsys, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["run_discovery.py", "--list-modules"],
    )

    run_discovery.main()

    out = capsys.readouterr().out
    assert "=== Available Adapters ===" in out
    assert "ua_phone" in out
    assert "=== Presets" in out


def test_run_discovery_emits_legacy_warning_by_default(capsys, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["run_discovery.py", "--list-modules"],
    )

    run_discovery.main()

    err = capsys.readouterr().err
    assert "[legacy]" in err
    assert "./scripts/hanna" in err


def test_run_discovery_can_suppress_legacy_warning(capsys, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["run_discovery.py", "--list-modules", "--no-legacy-warning"],
    )

    run_discovery.main()

    err = capsys.readouterr().err
    assert err == ""