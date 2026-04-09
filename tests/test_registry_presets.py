from registry import (
    CORE_LOCAL_MODULES,
    FULL_SPECTRUM_LOCAL_MODULES,
    MODULE_PRESETS,
    is_core_safe,
    is_disabled_module,
    resolve_modules,
    split_core_and_non_core_modules,
)


def test_default_modules_resolve_to_minimal_core_local_pipeline():
    assert resolve_modules(None) == CORE_LOCAL_MODULES
    assert CORE_LOCAL_MODULES == ["subfinder", "httpx_probe", "naabu", "nmap"]


def test_full_spectrum_excludes_external_api_and_broken_auto_modules():
    full_spectrum = MODULE_PRESETS["full-spectrum"]

    for module_name in [
        "getcontact",
        "ghunt",
        "social_analyzer",
        "search4faces",
        "web_search",
        "hibp",
        "shodan",
        "censys",
        "firms",
        "opendatabot",
    ]:
        assert module_name not in full_spectrum

    assert full_spectrum == FULL_SPECTRUM_LOCAL_MODULES


def test_optional_enrichment_preset_is_explicit_and_not_default():
    assert MODULE_PRESETS["enrich-optional"] == [
        "getcontact",
        "holehe",
        "opendatabot",
        "shodan",
        "censys",
        "hibp",
    ]
    assert resolve_modules(None) != MODULE_PRESETS["enrich-optional"]


def test_core_guard_and_disabled_module_contracts():
    assert all(is_core_safe(module_name) for module_name in CORE_LOCAL_MODULES)
    assert is_disabled_module("social_analyzer") is True


def test_split_core_and_non_core_modules_separates_enrichment():
    core, deferred = split_core_and_non_core_modules(["subfinder", "shodan", "nmap"])

    assert core == ["subfinder", "nmap"]
    assert deferred == ["shodan"]