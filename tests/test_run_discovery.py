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