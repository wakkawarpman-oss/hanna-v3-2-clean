from __future__ import annotations

from registry import MODULE_PRESETS, resolve_modules


def test_resolve_modules_default_excludes_getcontact_alias():
    resolved = resolve_modules(None)

    assert "ua_phone" in resolved
    assert "getcontact" not in resolved


def test_full_spectrum_preset_excludes_getcontact_alias():
    resolved = resolve_modules(["full-spectrum"])

    assert resolved == MODULE_PRESETS["full-spectrum"]
    assert "ua_phone" in resolved
    assert "getcontact" not in resolved