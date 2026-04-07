"""
registry.py — Single source of truth for adapter registration, presets, and scheduling.

All module lookups, lane assignments, and priority matrices live here.
To add a new adapter: register it in adapters/__init__.py, then add entries below.
"""
from __future__ import annotations

from adapters.base import ReconAdapter
from adapters.amass_adapter import AmassAdapter
from adapters.ashok import AshokAdapter
from adapters.avito import AvitoAdapter
from adapters.blackbird import BlackbirdAdapter
from adapters.censys_adapter import CensysAdapter
from adapters.eyewitness_adapter import EyewitnessAdapter
from adapters.firms import FIRMSAdapter
from adapters.ghunt import GHuntAdapter
from adapters.holehe_adapter import HoleheAdapter
from adapters.httpx_probe import HttpxAdapter
from adapters.katana import KatanaAdapter
from adapters.maryam import MaryamAdapter
from adapters.metagoofil_adapter import MetagoofilAdapter
from adapters.naabu import NaabuAdapter
from adapters.nmap_adapter import NmapAdapter
from adapters.nuclei import NucleiAdapter
from adapters.opendatabot import OpenDataBotAdapter
from adapters.reconng import ReconNGAdapter
from adapters.ru_leak import RULeakAdapter
from adapters.satintel import SatIntelAdapter
from adapters.search4faces import Search4FacesAdapter
from adapters.shodan_adapter import ShodanAdapter
from adapters.social_analyzer import SocialAnalyzerAdapter
from adapters.subfinder_adapter import SubfinderAdapter
from adapters.ua_leak import UALeakAdapter
from adapters.ua_phone import UAPhoneAdapter
from adapters.vk_graph import VKGraphAdapter
from adapters.web_search import WebSearchAdapter

ADAPTER_REGISTRY: dict[str, type[ReconAdapter]] = {
    "ua_leak": UALeakAdapter,
    "ru_leak": RULeakAdapter,
    "vk_graph": VKGraphAdapter,
    "avito": AvitoAdapter,
    "ua_phone": UAPhoneAdapter,
    "getcontact": UAPhoneAdapter,
    "maryam": MaryamAdapter,
    "ashok": AshokAdapter,
    "ghunt": GHuntAdapter,
    "social_analyzer": SocialAnalyzerAdapter,
    "satintel": SatIntelAdapter,
    "search4faces": Search4FacesAdapter,
    "web_search": WebSearchAdapter,
    "opendatabot": OpenDataBotAdapter,
    "firms": FIRMSAdapter,
    "nuclei": NucleiAdapter,
    "katana": KatanaAdapter,
    "httpx_probe": HttpxAdapter,
    "naabu": NaabuAdapter,
    "blackbird": BlackbirdAdapter,
    "holehe": HoleheAdapter,
    "censys": CensysAdapter,
    "metagoofil": MetagoofilAdapter,
    "subfinder": SubfinderAdapter,
    "amass": AmassAdapter,
    "nmap": NmapAdapter,
    "shodan": ShodanAdapter,
    "reconng": ReconNGAdapter,
    "eyewitness": EyewitnessAdapter,
}

# Re-export so callers can do `from registry import MODULES`
MODULES: dict[str, type[ReconAdapter]] = ADAPTER_REGISTRY
MODULE_ALIASES: dict[str, str] = {"getcontact": "ua_phone"}


def _default_module_names() -> list[str]:
    return [name for name in MODULES.keys() if name not in MODULE_ALIASES]

# ── Presets ──────────────────────────────────────────────────────

MODULE_PRESETS: dict[str, list[str]] = {
    "deep-ua": ["ua_leak", "ua_phone", "opendatabot"],
    "deep-ru": ["ru_leak", "vk_graph", "avito"],
    "deep-all": ["ua_leak", "ua_phone", "ru_leak", "vk_graph", "avito"],
    "leaks_all": ["ua_leak", "ru_leak"],
    "milint": [
        "maryam", "ashok", "ghunt", "social_analyzer",
        "satintel", "search4faces", "opendatabot",
    ],
    "infra": ["ashok", "maryam"],
    "geoint": ["satintel", "firms"],
    "social-deep": ["social_analyzer", "search4faces", "ghunt"],
    "fast-lane": [
        "ua_phone", "ua_leak", "ru_leak", "ghunt", "satintel",
        "avito", "maryam", "search4faces", "opendatabot",
    ],
    "slow-lane": ["ashok", "vk_graph", "social_analyzer", "web_search", "firms"],
    "pd-infra-quick": ["httpx_probe", "katana", "nuclei", "naabu"],
    "pd-infra-deep": ["httpx_probe", "katana", "nuclei", "naabu"],
    "pd-infra": ["httpx_probe", "katana", "nuclei", "naabu"],
    "pd-full": ["httpx_probe", "katana", "nuclei", "naabu", "ashok"],
    "person-deep": ["ua_phone", "ghunt", "holehe", "blackbird", "search4faces", "social_analyzer"],
    "email-chain": ["holehe", "ghunt", "metagoofil"],
    "subdomain-full": ["subfinder", "amass", "ashok"],
    "port-scan": ["naabu", "nmap"],
    "infra-deep": ["subfinder", "httpx_probe", "nuclei", "nmap", "shodan", "censys"],
    "recon-auto-quick": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"],
    "recon-auto-deep": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"],
    "recon-auto": ["subfinder", "httpx_probe", "nuclei", "katana", "naabu"],
    "full-spectrum-2026": _default_module_names(),
    "full-spectrum": _default_module_names(),
}

# ── Priority matrix (ROI-based) ─────────────────────────────────
# P0=Critical (target infrastructure), P1=High (regional leaks),
# P2=Medium (social deep dive), P3=Low (broad search)

MODULE_PRIORITY: dict[str, int] = {
    "ashok": 0,
    "ua_leak": 1,
    "ua_phone": 1,
    "getcontact": 1,
    "ru_leak": 1,
    "web_search": 1,
    "firms": 1,
    "opendatabot": 1,
    "nuclei": 1,
    "httpx_probe": 1,
    "naabu": 1,
    "subfinder": 1,
    "amass": 1,
    "shodan": 1,
    "censys": 1,
    "holehe": 1,
    "nmap": 0,
    "vk_graph": 2,
    "avito": 2,
    "ghunt": 2,
    "satintel": 2,
    "search4faces": 2,
    "katana": 2,
    "blackbird": 2,
    "metagoofil": 2,
    "reconng": 2,
    "social_analyzer": 3,
    "maryam": 3,
    "eyewitness": 3,
}

# ── Lane assignment ──────────────────────────────────────────────

MODULE_LANE: dict[str, str] = {
    "ua_phone": "fast",
    "getcontact": "fast",
    "ua_leak": "fast",
    "ru_leak": "fast",
    "ghunt": "fast",
    "satintel": "fast",
    "avito": "fast",
    "maryam": "fast",
    "search4faces": "fast",
    "opendatabot": "fast",
    "httpx_probe": "fast",
    "naabu": "fast",
    "subfinder": "fast",
    "shodan": "fast",
    "censys": "fast",
    "holehe": "fast",
    "blackbird": "fast",
    "ashok": "slow",
    "vk_graph": "slow",
    "social_analyzer": "slow",
    "web_search": "slow",
    "firms": "slow",
    "nuclei": "slow",
    "katana": "slow",
    "metagoofil": "slow",
    "amass": "slow",
    "nmap": "slow",
    "reconng": "slow",
    "eyewitness": "slow",
}

LANE_ORDER: dict[str, int] = {"fast": 0, "slow": 1}


def resolve_modules(names: list[str] | None) -> list[str]:
    """Resolve a list of module names / preset names into concrete module names."""
    if not names:
        return _default_module_names()
    if len(names) == 1 and names[0] in MODULE_PRESETS:
        return MODULE_PRESETS[names[0]]
    resolved: list[str] = []
    for n in names:
        if n in MODULE_PRESETS:
            resolved.extend(MODULE_PRESETS[n])
        elif n in MODULES:
            resolved.append(n)
    return list(dict.fromkeys(resolved))  # dedup preserving order
