from __future__ import annotations

import json
from pathlib import Path

from registry import MODULE_PRESETS, resolve_modules
from registry import MODULE_ALIASES, MODULE_LANE, MODULE_PRIORITY, MODULES


def test_resolve_modules_default_excludes_getcontact_alias():
    resolved = resolve_modules(None)

    assert "ua_phone" in resolved
    assert "getcontact" not in resolved


def test_full_spectrum_preset_excludes_getcontact_alias():
    resolved = resolve_modules(["full-spectrum"])

    assert resolved == MODULE_PRESETS["full-spectrum"]
    assert "ua_phone" in resolved
    assert "getcontact" not in resolved


def test_email_chain_includes_hibp():
    resolved = resolve_modules(["email-chain"])

    assert "hibp" in resolved


def test_node_adapter_catalog_matches_python_registry():
    catalog_path = Path(__file__).resolve().parents[1] / "config" / "adapter-catalog.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = {item["id"]: item for item in payload["adapters"]}

    expected_ids = {name for name in MODULES if name not in MODULE_ALIASES}

    assert set(catalog) == expected_ids
    for adapter_id, item in catalog.items():
        assert item["lane"] == MODULE_LANE[adapter_id]
        assert item["priority"] == MODULE_PRIORITY[adapter_id]