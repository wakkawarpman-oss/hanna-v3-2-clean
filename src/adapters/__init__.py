"""
adapters — ReconAdapter subclasses for HANNA deep reconnaissance.

Re-exports every adapter class and provides ADAPTER_REGISTRY for
name → class lookup.
"""
from __future__ import annotations

from adapters.base import (
    ReconAdapter,
    ReconHit,
    ReconReport,
    extract_phones_from_text,
    extract_validated_phones,
    normalize_phone,
)
from adapters.ua_leak import UALeakAdapter
from adapters.ru_leak import RULeakAdapter
from adapters.vk_graph import VKGraphAdapter
from adapters.avito import AvitoAdapter
from adapters.ua_phone import UAPhoneAdapter
from adapters.maryam import MaryamAdapter
from adapters.ashok import AshokAdapter
from adapters.ghunt import GHuntAdapter
from adapters.social_analyzer import SocialAnalyzerAdapter
from adapters.satintel import SatIntelAdapter
from adapters.search4faces import Search4FacesAdapter
from adapters.web_search import WebSearchAdapter
from adapters.opendatabot import OpenDataBotAdapter
from adapters.firms import FIRMSAdapter
from adapters.nuclei import NucleiAdapter
from adapters.katana import KatanaAdapter
from adapters.httpx_probe import HttpxAdapter
from adapters.naabu import NaabuAdapter
from adapters.blackbird import BlackbirdAdapter
from adapters.holehe_adapter import HoleheAdapter
from adapters.censys_adapter import CensysAdapter
from adapters.metagoofil_adapter import MetagoofilAdapter
from adapters.subfinder_adapter import SubfinderAdapter
from adapters.amass_adapter import AmassAdapter
from adapters.nmap_adapter import NmapAdapter
from adapters.shodan_adapter import ShodanAdapter
from adapters.reconng import ReconNGAdapter
from adapters.eyewitness_adapter import EyewitnessAdapter

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

__all__ = [
    "ReconAdapter",
    "ReconHit",
    "ReconReport",
    "normalize_phone",
    "extract_phones_from_text",
    "extract_validated_phones",
    "UALeakAdapter",
    "RULeakAdapter",
    "VKGraphAdapter",
    "AvitoAdapter",
    "UAPhoneAdapter",
    "MaryamAdapter",
    "AshokAdapter",
    "GHuntAdapter",
    "SocialAnalyzerAdapter",
    "SatIntelAdapter",
    "Search4FacesAdapter",
    "WebSearchAdapter",
    "OpenDataBotAdapter",
    "FIRMSAdapter",
    "NucleiAdapter",
    "KatanaAdapter",
    "HttpxAdapter",
    "NaabuAdapter",
    "BlackbirdAdapter",
    "HoleheAdapter",
    "CensysAdapter",
    "MetagoofilAdapter",
    "SubfinderAdapter",
    "AmassAdapter",
    "NmapAdapter",
    "ShodanAdapter",
    "ReconNGAdapter",
    "EyewitnessAdapter",
    "ADAPTER_REGISTRY",
]
