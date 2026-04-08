"""Preflight checks for external tool binaries and adapter prerequisites."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from shutil import which

from adapters.cli_common import COMMON_BIN_DIRS
from registry import resolve_modules


@dataclass
class PreflightCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


MODULE_CHECKS: dict[str, set[str]] = {
    "ua_phone": {"telegram_bot_token", "getcontact_token", "getcontact_aes_key"},
    "getcontact": {"telegram_bot_token", "getcontact_token", "getcontact_aes_key"},
    "nuclei": {"nuclei"},
    "katana": {"katana"},
    "httpx_probe": {"httpx_probe"},
    "naabu": {"naabu"},
    "subfinder": {"subfinder"},
    "amass": {"amass"},
    "nmap": {"nmap"},
    "shodan": {"shodan", "shodan_api_key"},
    "holehe": {"holehe"},
    "blackbird": {"blackbird"},
    "reconng": {"reconng"},
    "metagoofil": {"metagoofil"},
    "eyewitness": {"eyewitness", "eyewitness.chrome"},
    "censys": {"censys_api_id", "censys_api_secret"},
}


def _build_path() -> str:
    parts = [p for p in os.environ.get("PATH", "").split(":") if p]
    for item in COMMON_BIN_DIRS:
        if item not in parts:
            parts.append(item)
    return ":".join(parts)


def _resolve_env_binary(env_name: str, fallback: str) -> tuple[str | None, str]:
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return (env_value if Path(env_value).exists() or "/" not in env_value else None), f"env:{env_name}"
    resolved = which(fallback, path=_build_path())
    if resolved:
        return resolved, "path"
    return None, "missing"


def _filter_checks(checks: list[PreflightCheck], modules: list[str] | None) -> list[PreflightCheck]:
    if not modules:
        return checks
    resolved = resolve_modules(modules)
    wanted: set[str] = set()
    for module_name in resolved:
        wanted.update(MODULE_CHECKS.get(module_name, {module_name}))
    return [check for check in checks if check.name in wanted]


def run_preflight(modules: list[str] | None = None) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    tool_specs = [
        ("nuclei", "NUCLEI_BIN", "nuclei"),
        ("katana", "KATANA_BIN", "katana"),
        ("httpx_probe", "HTTPX_BIN", "httpx"),
        ("naabu", "NAABU_BIN", "naabu"),
        ("subfinder", "SUBFINDER_BIN", "subfinder"),
        ("amass", "AMASS_BIN", "amass"),
        ("nmap", "NMAP_BIN", "nmap"),
        ("shodan", "SHODAN_BIN", "shodan"),
        ("holehe", "HOLEHE_BIN", "holehe"),
    ]
    for name, env_name, fallback in tool_specs:
        resolved, source = _resolve_env_binary(env_name, fallback)
        checks.append(PreflightCheck(name=name, status="ok" if resolved else "fail", detail=resolved or source))

    repo_tools = [
        ("blackbird", "BLACKBIRD_BIN", Path("tools/blackbird/blackbird.py"), Path("tools/blackbird/.venv/bin/python")),
        ("reconng", "RECONNG_BIN", Path("tools/recon-ng/recon-ng"), Path("tools/recon-ng/.venv/bin/python")),
        ("metagoofil", "METAGOOFIL_BIN", Path("tools/metagoofil/metagoofil.py"), Path("tools/metagoofil/.venv/bin/python")),
        ("eyewitness", "EYEWITNESS_BIN", Path("tools/EyeWitness/Python/EyeWitness.py"), Path("tools/EyeWitness/eyewitness-venv/bin/python")),
    ]
    cwd = Path(__file__).resolve().parent.parent
    for name, env_name, script_rel, venv_rel in repo_tools:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            checks.append(PreflightCheck(name=name, status="ok", detail=f"env:{env_name}={env_value}"))
            continue
        script_path = cwd / script_rel
        venv_path = cwd / venv_rel if venv_rel else None
        path_hit = which(name if name != "reconng" else "recon-ng", path=_build_path())
        if script_path.exists() and (venv_path is None or venv_path.exists()):
            checks.append(PreflightCheck(name=name, status="ok", detail=f"repo:{script_path}"))
        elif path_hit:
            checks.append(PreflightCheck(name=name, status="warn", detail=f"path:{path_hit}"))
        else:
            checks.append(PreflightCheck(name=name, status="fail", detail="missing repo checkout and PATH binary"))

    chrome_bin = os.environ.get("EYEWITNESS_CHROME_BIN", "").strip()
    if chrome_bin:
        checks.append(PreflightCheck(
            name="eyewitness.chrome",
            status="ok" if Path(chrome_bin).exists() else "fail",
            detail=chrome_bin,
        ))
    else:
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        found = next((candidate for candidate in candidates if Path(candidate).exists()), "")
        checks.append(PreflightCheck(
            name="eyewitness.chrome",
            status="ok" if found else "warn",
            detail=found or "set EYEWITNESS_CHROME_BIN",
        ))

    for env_name in ["CENSYS_API_ID", "CENSYS_API_SECRET", "SHODAN_API_KEY"]:
        checks.append(PreflightCheck(
            name=env_name.lower(),
            status="ok" if os.environ.get(env_name, "").strip() else "warn",
            detail="set" if os.environ.get(env_name, "").strip() else f"missing {env_name}",
        ))

    ua_phone_envs = [
        ("telegram_bot_token", "TELEGRAM_BOT_TOKEN"),
        ("getcontact_token", "GETCONTACT_TOKEN"),
        ("getcontact_aes_key", "GETCONTACT_AES_KEY"),
    ]
    for check_name, env_name in ua_phone_envs:
        checks.append(PreflightCheck(
            name=check_name,
            status="ok" if os.environ.get(env_name, "").strip() else "warn",
            detail="set" if os.environ.get(env_name, "").strip() else f"missing {env_name}",
        ))
    return _filter_checks(checks, modules)


def has_hard_failures(checks: list[PreflightCheck]) -> bool:
    return any(check.status == "fail" for check in checks)


def preflight_summary(checks: list[PreflightCheck], modules: list[str] | None = None) -> dict[str, object]:
    return {
        "modules": modules or [],
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "total": len(checks),
            "ok": sum(1 for check in checks if check.status == "ok"),
            "warn": sum(1 for check in checks if check.status == "warn"),
            "fail": sum(1 for check in checks if check.status == "fail"),
            "has_hard_failures": has_hard_failures(checks),
        },
    }


def format_preflight_report(checks: list[PreflightCheck]) -> str:
    lines = ["=== Preflight ===", f"{'Name':<20} {'Status':<6} Detail", "-" * 72]
    for check in checks:
        lines.append(f"{check.name:<20} {check.status:<6} {check.detail}")
    failures = sum(1 for c in checks if c.status == "fail")
    warnings = sum(1 for c in checks if c.status == "warn")
    lines.append("")
    lines.append(f"Failures: {failures}  Warnings: {warnings}")
    return "\n".join(lines)