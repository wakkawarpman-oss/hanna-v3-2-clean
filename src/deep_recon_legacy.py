"""
deep_recon.py — UA + RU Deep Reconnaissance Adapter
====================================================

Phase 5: Target Expansion — searches Ukrainian and Russian data sources
for secondary phone numbers, leaked PII, social graph connections.

Architecture:
  - Each data source is a ReconAdapter subclass with .search() method
  - Results are ReconHit objects (observable_type, value, source, confidence)
  - All network access goes through configurable proxy (Tor/SOCKS5)
  - NO direct API keys stored — external config or env vars only

Modules:
  UA segment:
    - ua_leak:     OLX, Besplatka, Nova Poshta leak patterns
    - ua_phone:    GetContact/EyeCon reverse lookup
  RU segment:
    - ru_leak:     Yandex Food, SDEK, Delivery Club, VK leak patterns
    - vk_graph:    VK/OK social graph friend-list analysis
    - avito:       Avito/Yula marketplace scraper

Usage:
    from deep_recon import DeepReconRunner
    runner = DeepReconRunner(proxy="socks5h://127.0.0.1:9050")
    hits = runner.run(
        target_name="Hanna Dosenko",
        known_phones=["+380507133698"],
        known_usernames=["hannadosenko"],
        modules=["ua_leak", "ru_leak", "vk_graph"],
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import signal
import socket
import struct
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse
from abc import ABC, abstractmethod
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, Future, wait
from dataclasses import dataclass, field
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import (
    ADAPTER_REQ_CAP,
    ADAPTER_FAILURE_THRESHOLD,
    CROSS_CONFIRM_BOOST,
    MAX_JSONL_LINES,
    PRIORITY_WORKER_TIMEOUT,
    REQUIRE_PROXY,
    RETRY_BASE_DELAY,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
    RUNS_ROOT,
    WORKER_TIMEOUT,
)

log = logging.getLogger("hanna.recon")


# ── Data structures ──────────────────────────────────────────────

@dataclass
class ReconHit:
    """A single finding from a deep recon module."""
    observable_type: str     # phone, email, username, url, name
    value: str               # normalized value
    source_module: str       # which adapter found it
    source_detail: str       # e.g. "yandex_food_leak_2023"
    confidence: float        # 0.0 – 1.0
    raw_record: dict = field(default_factory=dict)  # full leak record for audit
    timestamp: str = ""      # when the record was created/found
    cross_refs: list[str] = field(default_factory=list)  # other observables in same record

    @property
    def fingerprint(self) -> str:
        return f"{self.observable_type}:{self.value}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to picklable dict."""
        return {
            "observable_type": self.observable_type,
            "value": self.value,
            "source_module": self.source_module,
            "source_detail": self.source_detail,
            "confidence": self.confidence,
            "raw_record": self.raw_record,
            "timestamp": self.timestamp,
            "cross_refs": self.cross_refs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReconHit:
        """Deserialize from dict."""
        return cls(
            observable_type=d["observable_type"],
            value=d["value"],
            source_module=d["source_module"],
            source_detail=d["source_detail"],
            confidence=d["confidence"],
            raw_record=d.get("raw_record", {}),
            timestamp=d.get("timestamp", ""),
            cross_refs=d.get("cross_refs", []),
        )


@dataclass
class ReconReport:
    """Aggregated result of a deep recon session."""
    target_name: str
    modules_run: list[str]
    hits: list[ReconHit]
    errors: list[dict]
    started_at: str
    finished_at: str = ""
    new_phones: list[str] = field(default_factory=list)
    new_emails: list[str] = field(default_factory=list)
    cross_confirmed: list[ReconHit] = field(default_factory=list)  # found in 2+ sources


# ── Phone normalization ──────────────────────────────────────────

_UA_PHONE_RE = re.compile(r"(?:\+?380|0)\d{9}")
_RU_PHONE_RE = re.compile(r"(?:\+?7|8)\d{10}")
_GENERIC_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{7,15}\d")


def normalize_phone(raw: str) -> str | None:
    """Normalize a phone string to E.164 format."""
    digits = re.sub(r"[\s\-\(\)\+]", "", raw)
    if not digits or len(digits) < 7:
        return None
    # UA: 0XXXXXXXXX or 380XXXXXXXXX
    if re.fullmatch(r"380\d{9}", digits):
        return f"+{digits}"
    if re.fullmatch(r"0\d{9}", digits) and digits[1] in "3456789":
        return f"+380{digits[1:]}"
    # RU: 7XXXXXXXXXX or 8XXXXXXXXXX
    if re.fullmatch(r"7\d{10}", digits):
        return f"+{digits}"
    if re.fullmatch(r"8\d{10}", digits):
        return f"+7{digits[1:]}"
    # Generic international
    if len(digits) >= 10:
        return f"+{digits}"
    return None


def extract_phones_from_text(text: str) -> list[str]:
    """Extract and normalize all phone numbers from text."""
    results = []
    seen = set()
    for pattern in [_UA_PHONE_RE, _RU_PHONE_RE, _GENERIC_PHONE_RE]:
        for m in pattern.finditer(text):
            norm = normalize_phone(m.group())
            if norm and norm not in seen:
                seen.add(norm)
                results.append(norm)
    return results


def extract_validated_phones(text: str) -> list[str]:
    """
    Extract ONLY real UA/RU phone numbers from raw HTML/text.
    Strict validation: rejects page IDs, prices, JS timestamps, CSS values.
    """
    results = []
    seen = set()

    # Only match well-formed UA/RU phone patterns
    # UA: +380XXXXXXXXX or 0XXXXXXXXX (with optional separators)
    # RU: +7XXXXXXXXXX or 8XXXXXXXXXX (with optional separators)
    strict_patterns = [
        re.compile(r'(?:^|\s|["\'>\(])(?:\+?380)[\s\-]?(\d{2})[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})(?:$|\s|["\<\)])'),
        re.compile(r'(?:^|\s|["\'>\(])(?:\+?7)[\s\-]?(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})(?:$|\s|["\<\)])'),
        # Common display formats
        re.compile(r'\+380\d{9}'),
        re.compile(r'\+7\d{10}'),
        re.compile(r'(?:^|\D)0[3-9]\d{8}(?:\D|$)'),  # UA local: 0XXXXXXXXX
    ]

    for pattern in strict_patterns:
        for m in pattern.finditer(text):
            raw = m.group()
            # Clean surrounding chars
            raw = re.sub(r'[^\d+]', '', raw) if '+' in raw else re.sub(r'[^\d]', '', raw)
            norm = normalize_phone(raw)
            if norm and norm not in seen:
                # Final validation: must be exactly +380XXXXXXXXX or +7XXXXXXXXXX
                if re.fullmatch(r'\+380\d{9}', norm) or re.fullmatch(r'\+7\d{10}', norm):
                    seen.add(norm)
                    results.append(norm)

    return results


# ── Base adapter ─────────────────────────────────────────────────

class ReconAdapter(ABC):
    """Base class for all recon data source adapters."""

    name: str = "base"
    region: str = "global"  # ua, ru, global

    # Per-adapter health tracking
    _consecutive_failures: int = 0
    _is_healthy: bool = True

    def __init__(self, proxy: str | None = None, timeout: float = 10.0, leak_dir: str | None = None):
        if REQUIRE_PROXY and not proxy:
            raise RuntimeError(
                f"HANNA_REQUIRE_PROXY=1 but no proxy provided to {self.__class__.__name__}. "
                "Set a proxy or unset HANNA_REQUIRE_PROXY to allow clearnet access."
            )
        self.proxy = proxy
        self.timeout = timeout
        self.leak_dir = Path(leak_dir) if leak_dir else None
        self._opener: urllib.request.OpenerDirector | None = None
        self._consecutive_failures = 0
        self._is_healthy = True
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy,
                "https": proxy,
            })
            self._opener = urllib.request.build_opener(proxy_handler)

    def _record_success(self) -> None:
        """Reset failure counter on successful request."""
        self._consecutive_failures = 0
        self._is_healthy = True

    def _record_failure(self) -> None:
        """Track consecutive failures; disable adapter after threshold."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= ADAPTER_FAILURE_THRESHOLD:
            self._is_healthy = False
            log.warning("%s: auto-disabled after %d consecutive failures", self.name, self._consecutive_failures)

    def _fetch(self, url: str, headers: dict | None = None) -> tuple[int, str]:
        """HTTP GET through proxy with retry. Returns (status_code, body)."""
        if not self._is_healthy:
            return 0, ""
        req = urllib.request.Request(url, headers=headers or {})
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0")
        last_status = 0
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                if self._opener:
                    resp = self._opener.open(req, timeout=self.timeout)
                else:
                    resp = urllib.request.urlopen(req, timeout=self.timeout)
                body = resp.read().decode("utf-8", errors="replace")
                self._record_success()
                return resp.status, body
            except urllib.error.HTTPError as e:
                last_status = e.code
                if e.code < 500:
                    self._record_failure()
                    return e.code, ""
                # 5xx: retry
            except (urllib.error.URLError, socket.timeout, OSError):
                pass
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5), RETRY_MAX_DELAY)
                time.sleep(delay)
        self._record_failure()
        return last_status, ""

    def _post(self, url: str, data: dict, headers: dict | None = None) -> tuple[int, str]:
        """HTTP POST (JSON body) through proxy with retry. Returns (status_code, body)."""
        if not self._is_healthy:
            return 0, ""
        payload = json.dumps(data).encode("utf-8")
        hdrs = dict(headers or {})
        hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0")
        last_status = 0
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                if self._opener:
                    resp = self._opener.open(req, timeout=self.timeout)
                else:
                    resp = urllib.request.urlopen(req, timeout=self.timeout)
                body = resp.read().decode("utf-8", errors="replace")
                self._record_success()
                return resp.status, body
            except urllib.error.HTTPError as e:
                last_status = e.code
                if e.code < 500:
                    self._record_failure()
                    return e.code, ""
            except (urllib.error.URLError, socket.timeout, OSError):
                pass
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5), RETRY_MAX_DELAY)
                time.sleep(delay)
        self._record_failure()
        return last_status, ""

    @abstractmethod
    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        """Run search and return findings."""
        ...


# ── UA Leak Adapter ──────────────────────────────────────────────

class UALeakAdapter(ReconAdapter):
    """
    Search Ukrainian leak databases and marketplace archives.

    Sources searched:
      - OLX.ua seller profiles (public phone exposure)
      - Nova Poshta sender/receiver leaks (2022-2024 dumps)
      - Besplatka.ua classifieds
      - Telegram bot aggregators (eye-of-god patterns)

    Strategy: name + city combination → phone cross-reference.
    """

    name = "ua_leak"
    region = "ua"

    # Known UA leak file patterns — searched locally in exports/leaks/ if present
    _LEAK_PATTERNS = [
        "nova_poshta_*.jsonl",
        "olx_sellers_*.jsonl",
        "besplatka_*.jsonl",
        "ukrnet_breach_*.jsonl",
    ]

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Scan local leak dumps if available
        leak_dir = self.leak_dir or (RUNS_ROOT / "leaks")
        if leak_dir.exists():
            hits.extend(self._scan_local_leaks(leak_dir, target_name, known_phones, known_usernames))

        # 2. OLX phone-to-name search (public ads API)
        hits.extend(self._search_olx(target_name, known_phones, known_usernames))

        return hits

    def _scan_local_leaks(
        self, leak_dir: Path, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Scan local JSONL leak files for matching records."""
        hits: list[ReconHit] = []
        name_parts = set(target_name.lower().split())
        known_set = set(known_phones)

        for pattern in self._LEAK_PATTERNS:
            for fpath in leak_dir.glob(pattern):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            if line_no > MAX_JSONL_LINES:  # safety cap
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            # Check if record matches target by name or username
                            record_text = json.dumps(record, ensure_ascii=False).lower()
                            name_match = all(part in record_text for part in name_parts)
                            username_match = any(u.lower() in record_text for u in known_usernames)

                            if not (name_match or username_match):
                                continue

                            # Extract phones from this record
                            phones_found = extract_phones_from_text(record_text)
                            new_phones = [p for p in phones_found if p not in known_set]

                            for phone in new_phones:
                                hits.append(ReconHit(
                                    observable_type="phone",
                                    value=phone,
                                    source_module=self.name,
                                    source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                    confidence=0.6 if name_match else 0.4,
                                    raw_record=record,
                                    timestamp=datetime.now().isoformat(),
                                    cross_refs=list(known_set),
                                ))

                            # Also extract emails
                            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", record_text)
                            for email in emails:
                                email = email.lower()
                                if "noreply" not in email and "example" not in email:
                                    hits.append(ReconHit(
                                        observable_type="email",
                                        value=email,
                                        source_module=self.name,
                                        source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                        confidence=0.5 if name_match else 0.3,
                                        raw_record=record,
                                        timestamp=datetime.now().isoformat(),
                                    ))
                except (OSError, PermissionError):
                    continue

        return hits

    def _search_olx(
        self, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Search OLX.ua for seller profiles matching target."""
        hits: list[ReconHit] = []
        # OLX search by username
        for username in known_usernames:
            encoded = urllib.parse.quote(username)
            url = f"https://www.olx.ua/d/uk/list/q-{encoded}/"
            status, body = self._fetch(url)
            if status == 200 and body:
                # Extract phones from OLX listing pages (strict UA/RU only)
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"olx_search:{username}",
                            confidence=0.45,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))
        return hits


# ── RU Leak Adapter ──────────────────────────────────────────────

class RULeakAdapter(ReconAdapter):
    """
    Search Russian leak databases.

    Sources:
      - VK.com profile data leaks (2019-2023)
      - Yandex Food / Delivery Club delivery leaks
      - SDEK shipping records
      - Mail.ru associated services

    Strategy: nickname search → phone extraction → cross-reference with UA phones.
    """

    name = "ru_leak"
    region = "ru"

    _LEAK_PATTERNS = [
        "vk_dump_*.jsonl",
        "yandex_food_*.jsonl",
        "delivery_club_*.jsonl",
        "sdek_*.jsonl",
        "mailru_*.jsonl",
    ]

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Local leak files
        leak_dir = self.leak_dir or (RUNS_ROOT / "leaks")
        if leak_dir.exists():
            hits.extend(self._scan_local_leaks(leak_dir, target_name, known_phones, known_usernames))

        # 2. VK public profile search
        hits.extend(self._search_vk_public(target_name, known_phones, known_usernames))

        return hits

    def _scan_local_leaks(
        self, leak_dir: Path, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Same logic as UA adapter but for RU leak patterns."""
        hits: list[ReconHit] = []
        name_parts = set(target_name.lower().split())
        known_set = set(known_phones)

        # Also transliterate name for Cyrillic matching
        cyrillic_variants = _transliterate_to_cyrillic(target_name)

        for pattern in self._LEAK_PATTERNS:
            for fpath in leak_dir.glob(pattern):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            if line_no > MAX_JSONL_LINES:
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            record_text = json.dumps(record, ensure_ascii=False).lower()

                            # Match: latin name parts OR cyrillic variants OR username
                            name_match = all(part in record_text for part in name_parts)
                            cyrillic_match = any(v.lower() in record_text for v in cyrillic_variants)
                            username_match = any(u.lower() in record_text for u in known_usernames)

                            if not (name_match or cyrillic_match or username_match):
                                continue

                            # Extract new phones
                            phones_found = extract_phones_from_text(record_text)
                            new_phones = [p for p in phones_found if p not in known_set]

                            base_conf = 0.55
                            if name_match and username_match:
                                base_conf = 0.75
                            elif cyrillic_match:
                                base_conf = 0.65

                            for phone in new_phones:
                                hits.append(ReconHit(
                                    observable_type="phone",
                                    value=phone,
                                    source_module=self.name,
                                    source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                    confidence=base_conf,
                                    raw_record=record,
                                    timestamp=datetime.now().isoformat(),
                                    cross_refs=list(known_set),
                                ))

                            # Also extract emails
                            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", record_text)
                            for email in emails:
                                email = email.lower()
                                if "noreply" not in email and "example" not in email:
                                    hits.append(ReconHit(
                                        observable_type="email",
                                        value=email,
                                        source_module=self.name,
                                        source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                        confidence=0.5 if name_match else 0.3,
                                        raw_record=record,
                                        timestamp=datetime.now().isoformat(),
                                    ))
                except (OSError, PermissionError):
                    continue

        return hits

    def _search_vk_public(
        self, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Search VK public people search for matching profiles."""
        hits: list[ReconHit] = []
        for username in known_usernames:
            # VK public page — no API key needed for public profiles
            url = f"https://vk.com/{urllib.parse.quote(username)}"
            status, body = self._fetch(url)
            if status == 200 and body:
                # Check if page actually belongs to target (not a generic 404-like page)
                name_lower = target_name.lower()
                body_lower = body.lower()

                # VK pages contain the name in <title> or og:title
                name_parts = name_lower.split()
                name_found = any(part in body_lower for part in name_parts if len(part) > 3)

                if name_found:
                    # Extract phone numbers shown on public profile (strict)
                    phones = extract_validated_phones(body)
                    known_set = set(known_phones)
                    for phone in phones:
                        if phone not in known_set:
                            hits.append(ReconHit(
                                observable_type="phone",
                                value=phone,
                                source_module=self.name,
                                source_detail=f"vk_profile:{username}",
                                confidence=0.7,
                                timestamp=datetime.now().isoformat(),
                                cross_refs=[username, url],
                            ))

                    # Extract linked contacts (Telegram, Instagram, etc.)
                    tg_matches = re.findall(r"t\.me/([a-zA-Z0-9_]{3,32})", body)
                    for tg in tg_matches:
                        hits.append(ReconHit(
                            observable_type="username",
                            value=tg,
                            source_module=self.name,
                            source_detail=f"vk_profile_link:{username}",
                            confidence=0.5,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))
        return hits


# ── VK Social Graph Adapter ──────────────────────────────────────

class VKGraphAdapter(ReconAdapter):
    """
    Analyze VK/OK social graph — friend lists, relatives, wall mentions.

    Strategy:
      1. Fetch public friend list from target's VK profile
      2. Scan friends' walls for target's phone mentions
      3. Check for "alternative contact" in target's info section
    """

    name = "vk_graph"
    region = "ru"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for username in known_usernames:
            # Fetch VK profile page
            url = f"https://vk.com/{urllib.parse.quote(username)}"
            status, body = self._fetch(url)
            if status != 200 or not body:
                continue

            # Extract VK user ID from page source
            uid_match = re.search(r'"rid":\s*(\d+)', body) or re.search(r'data-id="(\d+)"', body)
            if not uid_match:
                continue

            vk_uid = uid_match.group(1)

            # Fetch public friends list (no API key, limited to public profiles)
            friends_url = f"https://vk.com/friends?id={vk_uid}&section=all"
            f_status, f_body = self._fetch(friends_url)
            if f_status != 200 or not f_body:
                continue

            # Extract friend profile URLs
            friend_hrefs = set(re.findall(r'href="/([a-zA-Z0-9_.]+)"', f_body))
            # Cap at 50 to avoid abuse
            friend_hrefs = list(friend_hrefs)[:50]

            name_parts = set(target_name.lower().split())

            # Check each friend's wall for target's phone
            for friend_id in friend_hrefs[:20]:  # limit deep scan
                wall_url = f"https://vk.com/{friend_id}?w=wall"
                w_status, w_body = self._fetch(wall_url)
                if w_status != 200 or not w_body:
                    continue

                # Check if friend's wall mentions target's name
                w_lower = w_body.lower()
                if not any(part in w_lower for part in name_parts if len(part) > 3):
                    continue

                # Extract phones from wall context (strict UA/RU only)
                phones = extract_validated_phones(w_body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"vk_friend_wall:{friend_id}",
                            confidence=0.5,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username, friend_id],
                        ))

                time.sleep(0.5)  # rate limiting

        return hits


# ── Avito/Yula Marketplace Adapter ──────────────────────────────

class AvitoAdapter(ReconAdapter):
    """Search Avito.ru and Yula for seller profiles."""

    name = "avito"
    region = "ru"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Search Avito by name (public seller names are visible)
        for username in known_usernames:
            encoded = urllib.parse.quote(username)
            url = f"https://www.avito.ru/all?q={encoded}"
            status, body = self._fetch(url)
            if status == 200 and body:
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"avito_search:{username}",
                            confidence=0.4,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))

        # Name search (Cyrillic)
        cyrillic = _transliterate_to_cyrillic(target_name)
        for variant in cyrillic[:2]:
            encoded = urllib.parse.quote(variant)
            url = f"https://www.avito.ru/all?q={encoded}"
            status, body = self._fetch(url)
            if status == 200 and body:
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"avito_name_search:{variant}",
                            confidence=0.35,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[variant],
                        ))
        return hits


# ── UA Phone Reverse Lookup Adapter ─────────────────────────────

class UAPhoneAdapter(ReconAdapter):
    """
    Reverse phone lookup through UA-specific services.
    Checks GetContact tags, EyeCon, Telegram phone-to-account linking.

    Live methods require env vars:
      - TELEGRAM_BOT_TOKEN  → Bot API phone resolution
      - GETCONTACT_API_KEY  → GetContact tag lookup
    If env vars are absent, the adapter falls back to the passive stub.
    """

    name = "ua_phone"
    region = "ua"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        for phone in known_phones:
            # 1) Live Telegram phone→username resolution
            tg_hits = self._check_telegram_phone_live(phone, target_name)
            hits.extend(tg_hits)

            # 2) GetContact tag lookup
            gc_hits = self._check_getcontact_phone(phone, target_name)
            hits.extend(gc_hits)

        return hits

    # ── Telegram live resolution ─────────────────────────────────

    def _check_telegram_phone_live(
        self, phone: str, target_name: str
    ) -> list[ReconHit]:
        """
        Resolve phone→Telegram user via Bot API getChat or contacts.resolvePhone.
        Requires TELEGRAM_BOT_TOKEN env var.  Falls back to passive stub if absent.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            # Passive stub — log for manual follow-up
            return [ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail="telegram_phone_check:pending",
                confidence=0.0,
                timestamp=datetime.now().isoformat(),
                raw_record={"action": "manual_check_required", "service": "telegram", "phone": phone},
            )]

        # Use Telegram Bot API — getChat with phone (unofficial but widespread)
        # The reliable method: create a temporary contact and resolve via getContacts
        # Bot API doesn't expose phone→user directly, so we use the
        # phone_number_privacy workaround: try sending a contact to a
        # helper chat and observing the user_id resolution.
        #
        # Simplified approach: call getChat with the phone-derived user search
        # This is a best-effort check.
        url = f"https://api.telegram.org/bot{token}/getChat"
        try:
            status, body = self._post(url, data={"chat_id": phone})
            if status == 200 and body:
                result = json.loads(body).get("result", {})
                username = result.get("username", "")
                first_name = result.get("first_name", "")
                last_name = result.get("last_name", "")
                full_name = f"{first_name} {last_name}".strip().lower()

                # Check name similarity
                name_parts = set(target_name.lower().split())
                name_match = any(p in full_name for p in name_parts if len(p) > 2)

                conf = 0.7 if name_match else 0.3
                hits = []
                if username:
                    hits.append(ReconHit(
                        observable_type="username",
                        value=username,
                        source_module=self.name,
                        source_detail=f"telegram_bot_api:phone={phone}",
                        confidence=conf,
                        timestamp=datetime.now().isoformat(),
                        raw_record=result,
                        cross_refs=[phone],
                    ))
                if full_name and name_match:
                    hits.append(ReconHit(
                        observable_type="phone",
                        value=phone,
                        source_module=self.name,
                        source_detail=f"telegram_bot_api:name_confirmed",
                        confidence=0.85,
                        timestamp=datetime.now().isoformat(),
                        raw_record=result,
                        cross_refs=[username] if username else [],
                    ))
                return hits if hits else [ReconHit(
                    observable_type="phone",
                    value=phone,
                    source_module=self.name,
                    source_detail="telegram_bot_api:no_match",
                    confidence=0.1,
                    timestamp=datetime.now().isoformat(),
                    raw_record=result,
                )]
        except Exception:
            pass

        return [ReconHit(
            observable_type="phone",
            value=phone,
            source_module=self.name,
            source_detail="telegram_phone_check:api_error",
            confidence=0.0,
            timestamp=datetime.now().isoformat(),
            raw_record={"action": "api_call_failed", "service": "telegram", "phone": phone},
        )]

    # ── GetContact lookup ────────────────────────────────────────

    def _check_getcontact_phone(
        self, phone: str, target_name: str
    ) -> list[ReconHit]:
        """
        Check GetContact for contact-book tags associated with the phone.
        Requires GETCONTACT_API_KEY env var.  Silently skips if absent.
        """
        api_key = os.environ.get("GETCONTACT_API_KEY", "").strip()
        if not api_key:
            return []

        # GetContact v2 API — search by phone number
        url = "https://pbssrv-centralus.azurewebsites.net/v3/search"
        headers = {
            "X-Req-Timestamp": str(int(datetime.now().timestamp())),
            "X-Token": api_key,
        }
        try:
            status, body = self._post(
                url,
                data={"phoneNumber": phone, "source": ""},
                headers=headers,
            )
            if status != 200 or not body:
                return []

            data = json.loads(body)
            tags = data.get("result", {}).get("tags", [])
            if not tags:
                return []

            # Check if any tag references the target name
            name_parts = set(target_name.lower().split())
            hits: list[ReconHit] = []

            for tag_obj in tags[:10]:  # cap at 10 tags
                tag = tag_obj if isinstance(tag_obj, str) else tag_obj.get("tag", "")
                tag_lower = tag.lower()
                name_match = any(p in tag_lower for p in name_parts if len(p) > 2)
                conf = 0.75 if name_match else 0.2
                hits.append(ReconHit(
                    observable_type="phone",
                    value=phone,
                    source_module=self.name,
                    source_detail=f"getcontact:tag={tag[:50]}",
                    confidence=conf,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"tag": tag, "phone": phone, "name_match": name_match},
                    cross_refs=[],
                ))

            return hits

        except Exception:
            return []


# ── Maryam Adapter (OWASP Framework) ────────────────────────────

class MaryamAdapter(ReconAdapter):
    """
    OWASP Maryam — modular OSINT framework integration.

    Wraps the `maryam` CLI to run modules:
      - dns_search:   DNS enumeration for domains associated with target
      - email_search: Email discovery via search-engine dorking
      - social_nets:  Social network profile discovery
      - web_search:   Alternative search engines (DuckDuckGo, Bing, Yahoo)

    Primary purpose: re-check soft_match links through alternative
    search engines to confirm or kill them.

    Requires: pip install maryam  (or git clone + setup.py)
    """

    name = "maryam"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Search by target name via web_search module
        hits.extend(self._run_web_search(target_name))

        # 2. Search by known usernames (alternative engine verification)
        for username in known_usernames:
            hits.extend(self._run_web_search(username))

        # 3. Email search — dorking for associated emails
        hits.extend(self._run_email_search(target_name))

        # 4. Social nets scan
        for username in known_usernames:
            hits.extend(self._run_social_nets(username))

        return hits

    def _run_maryam_module(self, module: str, query: str) -> str | None:
        """Execute a Maryam module via CLI and capture JSON output."""
        maryam_bin = os.environ.get("MARYAM_BIN", "maryam")
        cmd = [maryam_bin, "-e", module, "-q", query, "-o", "json"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout * 3,
                start_new_session=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except subprocess.TimeoutExpired as exc:
            if exc.args and hasattr(exc, 'cmd'):
                _kill_process_group(exc)
        except (FileNotFoundError, OSError):
            pass
        return None

    def _run_web_search(self, query: str) -> list[ReconHit]:
        """Search alternative engines (DuckDuckGo, Bing) for the target."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("web_search", query)
        if not output:
            # Fallback: direct DuckDuckGo HTML search
            return self._fallback_ddg_search(query)

        try:
            data = json.loads(output)
            results = data if isinstance(data, list) else data.get("results", [])
            for item in results[:20]:
                url = item.get("url", item.get("link", ""))
                if url:
                    hits.append(ReconHit(
                        observable_type="url",
                        value=url,
                        source_module=self.name,
                        source_detail=f"web_search:{query[:30]}",
                        confidence=0.35,
                        timestamp=datetime.now().isoformat(),
                        raw_record=item,
                        cross_refs=[query],
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits

    def _fallback_ddg_search(self, query: str) -> list[ReconHit]:
        """Direct DuckDuckGo HTML scrape when Maryam is unavailable."""
        hits: list[ReconHit] = []
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status != 200 or not body:
            return hits

        # Extract result links from DDG HTML
        link_pattern = re.compile(r'class="result__a"[^>]*href="([^"]+)"')
        for m in link_pattern.finditer(body):
            href = m.group(1)
            # DDG wraps links in redirects — extract actual URL
            parsed = urllib.parse.urlparse(href)
            params = urllib.parse.parse_qs(parsed.query)
            actual = params.get("uddg", [href])[0]
            if actual.startswith("http"):
                hits.append(ReconHit(
                    observable_type="url",
                    value=actual,
                    source_module=self.name,
                    source_detail=f"ddg_fallback:{query[:30]}",
                    confidence=0.3,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"query": query, "url": actual},
                    cross_refs=[query],
                ))
        return hits[:15]

    def _run_email_search(self, query: str) -> list[ReconHit]:
        """Dork for emails associated with a name/domain."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("email_search", query)
        if not output:
            return hits
        try:
            data = json.loads(output)
            emails = data if isinstance(data, list) else data.get("emails", [])
            for email_val in emails:
                email_str = email_val if isinstance(email_val, str) else email_val.get("email", "")
                if "@" in email_str and "noreply" not in email_str.lower():
                    hits.append(ReconHit(
                        observable_type="email",
                        value=email_str.lower(),
                        source_module=self.name,
                        source_detail=f"email_search:{query[:30]}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"query": query, "email": email_str},
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits

    def _run_social_nets(self, username: str) -> list[ReconHit]:
        """Check social networks for a username."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("social_nets", username)
        if not output:
            return hits
        try:
            data = json.loads(output)
            profiles = data if isinstance(data, list) else data.get("profiles", data.get("results", []))
            for profile in profiles[:30]:
                url = profile.get("url", profile.get("link", "")) if isinstance(profile, dict) else str(profile)
                if url and url.startswith("http"):
                    hits.append(ReconHit(
                        observable_type="url",
                        value=url,
                        source_module=self.name,
                        source_detail=f"social_nets:{username}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record=profile if isinstance(profile, dict) else {"url": url},
                        cross_refs=[username],
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits


# ── Ashok Adapter (Infrastructure Recon) ─────────────────────────

class AshokAdapter(ReconAdapter):
    """
    Ashok — infrastructure reconnaissance tool integration.

    Capabilities:
      - Subdomain enumeration  (--subdomain)
      - CMS & headers analysis (detect WP, Joomla, analytics IDs)
      - Wayback Machine integration (archived pages, old contacts)
      - Google Analytics UA-ID reverse lookup for cross-site pivoting

    Filters: excludes common platforms (google.com, facebook.com, etc.)

    Requires: pip install ashok  (or git clone + setup.py)
    Env vars:
      ASHOK_BIN  — path to ashok executable (default: "ashok")
    """

    name = "ashok"
    region = "global"

    _IGNORE_DOMAINS = {
        "google.com", "facebook.com", "twitter.com", "instagram.com",
        "youtube.com", "linkedin.com", "github.com", "microsoft.com",
        "apple.com", "amazon.com", "cloudflare.com", "amazonaws.com",
        "googleusercontent.com", "gstatic.com", "fbcdn.net",
    }

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Extract domains from known usernames (could be domain-like)
        domains = self._extract_target_domains(target_name, known_usernames)

        for domain in domains:
            # 1. Subdomain enumeration
            hits.extend(self._enumerate_subdomains(domain))

            # 2. CMS & headers analysis
            hits.extend(self._analyze_headers(domain))

            # 3. Wayback Machine archived pages
            hits.extend(self._search_wayback(domain, target_name))

        # 4. Wayback search by name (not domain)
        hits.extend(self._search_wayback_by_name(target_name))

        return hits

    def _extract_target_domains(self, target_name: str, known_usernames: list[str]) -> list[str]:
        """Extract plausible domains from usernames or derive from target name."""
        domains: list[str] = []
        for uname in known_usernames:
            # If username looks like a domain
            if "." in uname and not uname.startswith("@"):
                base = uname.lower().split("/")[0]
                if base not in self._IGNORE_DOMAINS:
                    domains.append(base)
        # Also try common personal site patterns (ASCII only — skip Cyrillic names)
        name_slug = target_name.lower().replace(" ", "")
        if name_slug.isascii():
            for tld in [".com", ".ua", ".me"]:
                domains.append(f"{name_slug}{tld}")
        return domains[:5]

    def _run_ashok_cli(self, args: list[str]) -> str | None:
        """Run Ashok CLI tool with given arguments."""
        ashok_bin = os.environ.get("ASHOK_BIN", "ashok")
        cmd = [ashok_bin] + args
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout * 5,
                start_new_session=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(exc)
        except (FileNotFoundError, OSError):
            pass
        return None

    def _enumerate_subdomains(self, domain: str) -> list[ReconHit]:
        """Subdomain enumeration via Ashok CLI or crt.sh fallback."""
        hits: list[ReconHit] = []

        # Try Ashok CLI first
        output = self._run_ashok_cli(["--subdomain", domain])
        if output:
            for line in output.splitlines():
                sub = line.strip().lower()
                if sub and "." in sub and not any(ign in sub for ign in self._IGNORE_DOMAINS):
                    hits.append(ReconHit(
                        observable_type="infrastructure",
                        value=sub,
                        source_module=self.name,
                        source_detail=f"subdomain_enum:{domain}",
                        confidence=0.5,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "subdomain": sub},
                    ))
            return hits

        # Fallback: crt.sh certificate transparency search
        url = f"https://crt.sh/?q=%.{urllib.parse.quote(domain)}&output=json"
        status, body = self._fetch(url)
        if status == 200 and body:
            try:
                certs = json.loads(body)
                seen: set[str] = set()
                for cert in certs[:100]:
                    name_value = cert.get("name_value", "")
                    for sub in name_value.split("\n"):
                        sub = sub.strip().lower().lstrip("*.")
                        if sub and sub not in seen and sub != domain:
                            seen.add(sub)
                            if not any(ign in sub for ign in self._IGNORE_DOMAINS):
                                hits.append(ReconHit(
                                    observable_type="infrastructure",
                                    value=sub,
                                    source_module=self.name,
                                    source_detail=f"crt.sh:{domain}",
                                    confidence=0.45,
                                    timestamp=datetime.now().isoformat(),
                                    raw_record=cert,
                                ))
            except (json.JSONDecodeError, TypeError):
                pass

        return hits

    def _analyze_headers(self, domain: str) -> list[ReconHit]:
        """Fetch HTTP headers and detect CMS, analytics IDs, tech stack."""
        hits: list[ReconHit] = []
        for scheme in ("https", "http"):
            url = f"{scheme}://{domain}/"
            status, body = self._fetch(url)
            if status == 0:
                continue

            # Extract Google Analytics UA-IDs (cross-site correlation pivot)
            ua_ids = re.findall(r'UA-\d{4,10}-\d{1,4}', body)
            for ua_id in set(ua_ids):
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=ua_id,
                    source_module=self.name,
                    source_detail=f"analytics_id:{domain}",
                    confidence=0.65,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "analytics_id": ua_id, "type": "google_analytics"},
                ))

            # Detect GA4 measurement IDs
            ga4_ids = re.findall(r'G-[A-Z0-9]{10,12}', body)
            for ga4 in set(ga4_ids):
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=ga4,
                    source_module=self.name,
                    source_detail=f"ga4_id:{domain}",
                    confidence=0.65,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "analytics_id": ga4, "type": "ga4"},
                ))

            # CMS detection
            cms = self._detect_cms(body)
            if cms:
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=f"cms:{cms}@{domain}",
                    source_module=self.name,
                    source_detail=f"cms_detect:{domain}",
                    confidence=0.5,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "cms": cms},
                ))

            # Extract emails from page body
            emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', body)
            for email in set(emails):
                email = email.lower()
                if "noreply" not in email and "example" not in email and "wixpress" not in email:
                    hits.append(ReconHit(
                        observable_type="email",
                        value=email,
                        source_module=self.name,
                        source_detail=f"page_scrape:{domain}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "email": email},
                    ))

            # Extract phones from page
            phones = extract_validated_phones(body)
            for phone in phones:
                hits.append(ReconHit(
                    observable_type="phone",
                    value=phone,
                    source_module=self.name,
                    source_detail=f"page_scrape:{domain}",
                    confidence=0.4,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "phone": phone},
                ))

            break  # only need one scheme to succeed

        return hits

    @staticmethod
    def _detect_cms(html: str) -> str | None:
        """Detect CMS from HTML content signatures."""
        lower = html.lower()
        if "wp-content" in lower or "wordpress" in lower:
            return "wordpress"
        if "joomla" in lower:
            return "joomla"
        if "drupal" in lower:
            return "drupal"
        if "bitrix" in lower or "1c-bitrix" in lower:
            return "bitrix"
        if "tilda" in lower or "tildacdn" in lower:
            return "tilda"
        if "wix.com" in lower:
            return "wix"
        if "squarespace" in lower:
            return "squarespace"
        if "shopify" in lower:
            return "shopify"
        return None

    def _search_wayback(self, domain: str, target_name: str) -> list[ReconHit]:
        """Search Wayback Machine for archived pages with contact info."""
        hits: list[ReconHit] = []

        # Keep P0 breadth bounded: probe the highest-signal pages first.
        pages = ["about", "contact", "cv"]
        for page_slug in pages:
            cdx_url = (
                f"https://web.archive.org/cdx/search/cdx?"
                f"url={urllib.parse.quote(domain)}/{page_slug}*"
                f"&output=json&fl=timestamp,original&limit=3&collapse=urlkey"
            )
            status, body = self._fetch(cdx_url)
            if status != 200 or not body:
                continue

            try:
                rows = json.loads(body)
                for row in rows[1:]:  # skip header
                    ts, orig_url = row[0], row[1]
                    wb_url = f"https://web.archive.org/web/{ts}/{orig_url}"
                    hits.append(ReconHit(
                        observable_type="url",
                        value=wb_url,
                        source_module=self.name,
                        source_detail=f"wayback:{domain}/{page_slug}",
                        confidence=0.35,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "timestamp": ts, "url": orig_url, "wayback_url": wb_url},
                    ))
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        return hits

    def _search_wayback_by_name(self, target_name: str) -> list[ReconHit]:
        """Search Wayback CDX for any URL containing the target name."""
        hits: list[ReconHit] = []
        name_slug = target_name.lower().replace(" ", "-")
        alt_slug = target_name.lower().replace(" ", "_")

        for slug in (name_slug, alt_slug):
            cdx_url = (
                f"https://web.archive.org/cdx/search/cdx?"
                f"url=*{urllib.parse.quote(slug)}*"
                f"&output=json&fl=timestamp,original&limit=3&collapse=urlkey"
            )
            status, body = self._fetch(cdx_url)
            if status != 200 or not body:
                continue
            try:
                rows = json.loads(body)
                for row in rows[1:]:
                    ts, orig_url = row[0], row[1]
                    wb_url = f"https://web.archive.org/web/{ts}/{orig_url}"
                    hits.append(ReconHit(
                        observable_type="url",
                        value=wb_url,
                        source_module=self.name,
                        source_detail=f"wayback_name_search:{slug}",
                        confidence=0.3,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"slug": slug, "timestamp": ts, "url": orig_url},
                    ))
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        return hits


# ── GHunt Adapter (Google Account Recon) ─────────────────────────

class GHuntAdapter(ReconAdapter):
    """
    GHunt — Google account reconnaissance.

    From a known Gmail address, extracts:
      - Google Maps contributions and reviews
      - Public Google Photos albums
      - YouTube channel (if linked)
      - Device information (model/OS from sync metadata)
      - Google Calendar public events

    Requires: pip install ghunt  (+ OAuth cookie setup via ghunt login)
    Env vars:
      GHUNT_BIN       — path to ghunt executable (default: "ghunt")
      GHUNT_CREDS_DIR — directory with ghunt credentials
    """

    name = "ghunt"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Extract emails from known usernames
        emails = [u for u in known_usernames if "@" in u and "gmail" in u.lower()]

        # Also try constructing Gmail from name patterns
        name_parts = target_name.lower().split()
        if len(name_parts) >= 2 and not emails:
            emails.extend([
                f"{name_parts[0]}.{name_parts[1]}@gmail.com",
                f"{name_parts[0]}{name_parts[1]}@gmail.com",
            ])

        for email in emails[:3]:
            ghunt_data = self._run_ghunt_email(email)
            if ghunt_data:
                hits.extend(self._parse_ghunt_output(email, ghunt_data))
            else:
                # Manual fallback: check Google Maps reviews
                hits.extend(self._check_google_maps_profile(email, target_name))

        return hits

    def _run_ghunt_email(self, email: str) -> str | None:
        """Run GHunt CLI to profile a Gmail address."""
        ghunt_bin = os.environ.get("GHUNT_BIN", "ghunt")
        creds = os.environ.get("GHUNT_CREDS_DIR", "")
        cmd = [ghunt_bin, "email", email]
        if creds:
            cmd += ["--creds", creds]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout * 5,
                start_new_session=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(exc)
        except (FileNotFoundError, OSError):
            pass
        return None

    def _parse_ghunt_output(self, email: str, output: str) -> list[ReconHit]:
        """Parse GHunt text output for actionable intelligence."""
        hits: list[ReconHit] = []
        raw = {"email": email, "output_preview": output[:2000]}

        # Look for Google Maps profile
        maps_match = re.search(r'(https://www\.google\.com/maps/contrib/\d+)', output)
        if maps_match:
            hits.append(ReconHit(
                observable_type="url",
                value=maps_match.group(1),
                source_module=self.name,
                source_detail=f"ghunt:maps_contrib:{email}",
                confidence=0.75,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # YouTube channel
        yt_match = re.search(r'(https://www\.youtube\.com/channel/[\w-]+)', output)
        if yt_match:
            hits.append(ReconHit(
                observable_type="url",
                value=yt_match.group(1),
                source_module=self.name,
                source_detail=f"ghunt:youtube:{email}",
                confidence=0.7,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # Google Photos albums
        photos_matches = re.findall(r'(https://photos\.google\.com/[\w/]+)', output)
        for url in photos_matches[:3]:
            hits.append(ReconHit(
                observable_type="url",
                value=url,
                source_module=self.name,
                source_detail=f"ghunt:photos:{email}",
                confidence=0.65,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # Phones in output
        phones = extract_validated_phones(output)
        for phone in phones:
            hits.append(ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail=f"ghunt:phone:{email}",
                confidence=0.6,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # If GHunt ran but produced no structured hits, still note it
        if not hits:
            hits.append(ReconHit(
                observable_type="email",
                value=email,
                source_module=self.name,
                source_detail="ghunt:profile_exists",
                confidence=0.3,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
            ))

        return hits

    def _check_google_maps_profile(self, email: str, target_name: str) -> list[ReconHit]:
        """Fallback: search Google Maps for user reviews by name."""
        hits: list[ReconHit] = []
        encoded = urllib.parse.quote(f'"{target_name}" site:google.com/maps/contrib')
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status == 200 and body:
            maps_links = re.findall(r'https://www\.google\.com/maps/contrib/\d+', body)
            for link in list(set(maps_links))[:2]:
                hits.append(ReconHit(
                    observable_type="url",
                    value=link,
                    source_module=self.name,
                    source_detail=f"maps_search:{target_name}",
                    confidence=0.35,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"query": target_name, "url": link},
                ))
        return hits


# ── Social-Analyzer Adapter (1000+ networks) ────────────────────

class SocialAnalyzerAdapter(ReconAdapter):
    """
    Social-Analyzer — 1000+ social network username search.

    More aggressive than Maigret/Sherlock. Checks:
      - 1000+ social platforms simultaneously
      - Returns profile URL, name, existence confidence
      - CLI + JSON output mode

    Requires: pip install social-analyzer
    Env vars:
      SOCIAL_ANALYZER_BIN — path to executable (default: "social-analyzer")
    """

    name = "social_analyzer"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        for username in known_usernames:
            results = self._run_social_analyzer(username)
            if results:
                hits.extend(results)
            else:
                # Fallback: direct checks on key platforms
                hits.extend(self._fallback_platform_checks(username))

        return hits

    def _run_social_analyzer(self, username: str) -> list[ReconHit] | None:
        """Run social-analyzer CLI for a username."""
        sa_bin = os.environ.get("SOCIAL_ANALYZER_BIN", "social-analyzer")
        cmd = [
            sa_bin,
            "--username", username,
            "--metadata",
            "--output", "json",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout * 10,
                start_new_session=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return self._parse_sa_output(username, proc.stdout.strip())
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(exc)
        except (FileNotFoundError, OSError):
            pass
        return None

    def _parse_sa_output(self, username: str, output: str) -> list[ReconHit]:
        """Parse social-analyzer JSON output."""
        hits: list[ReconHit] = []
        try:
            data = json.loads(output)
            profiles = data if isinstance(data, list) else data.get("detected", data.get("results", []))
            for profile in profiles:
                if isinstance(profile, dict):
                    url = profile.get("link", profile.get("url", ""))
                    site = profile.get("site", profile.get("source", ""))
                    status = profile.get("status", "")
                    if url and url.startswith("http") and "not found" not in status.lower():
                        conf = 0.55 if status.lower() in ("found", "claimed", "available") else 0.3
                        hits.append(ReconHit(
                            observable_type="url",
                            value=url,
                            source_module=self.name,
                            source_detail=f"social_analyzer:{site or 'unknown'}",
                            confidence=conf,
                            timestamp=datetime.now().isoformat(),
                            raw_record=profile,
                            cross_refs=[username],
                        ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits[:50]

    def _fallback_platform_checks(self, username: str) -> list[ReconHit]:
        """Direct HTTP HEAD checks on popular platforms when CLI unavailable."""
        hits: list[ReconHit] = []
        platforms = {
            "tiktok": f"https://www.tiktok.com/@{urllib.parse.quote(username, safe='')}",
            "pinterest": f"https://www.pinterest.com/{urllib.parse.quote(username, safe='')}/",
            "reddit": f"https://www.reddit.com/user/{urllib.parse.quote(username, safe='')}",
            "medium": f"https://medium.com/@{urllib.parse.quote(username, safe='')}",
            "deviantart": f"https://www.deviantart.com/{urllib.parse.quote(username, safe='')}",
            "soundcloud": f"https://soundcloud.com/{urllib.parse.quote(username, safe='')}",
            "twitch": f"https://www.twitch.tv/{urllib.parse.quote(username, safe='')}",
            "vimeo": f"https://vimeo.com/{urllib.parse.quote(username, safe='')}",
            "flickr": f"https://www.flickr.com/people/{urllib.parse.quote(username, safe='')}/",
            "ok.ru": f"https://ok.ru/{urllib.parse.quote(username, safe='')}",
            "habr": f"https://habr.com/ru/users/{urllib.parse.quote(username, safe='')}/",
            "pikabu": f"https://pikabu.ru/@{urllib.parse.quote(username, safe='')}",
        }

        for platform, url in platforms.items():
            # Reddit returns 200 for all /user/ URLs (SPA); verify via JSON API
            if platform == "reddit":
                api_url = url.rstrip("/") + "/about.json"
                api_status, _ = self._fetch(api_url)
                if api_status != 200:
                    continue
            status, body = self._fetch(url)
            if status == 200 and body:
                body_lower = body.lower()
                if "page not found" in body_lower or "user not found" in body_lower or "404" in body_lower:
                    continue
                hits.append(ReconHit(
                    observable_type="url",
                    value=url,
                    source_module=self.name,
                    source_detail=f"direct_check:{platform}",
                    confidence=0.35,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"username": username, "platform": platform, "status": status},
                    cross_refs=[username],
                ))

        return hits


# ── SatIntel Adapter (GEOINT / EXIF) ────────────────────────────

class SatIntelAdapter(ReconAdapter):
    """
    Satellite Intelligence + EXIF GEOINT adapter.

    Capabilities:
      - EXIF GPS coordinate extraction from local image files
      - Reverse geocoding of extracted coordinates
      - Satellite overpass time queries (for imagery request planning)

    Env vars:
      SATINTEL_IMAGE_DIR — directory with target photos to analyze EXIF
    """

    name = "satintel"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Scan local images for EXIF GPS data
        image_dir = os.environ.get("SATINTEL_IMAGE_DIR", "")
        if image_dir:
            hits.extend(self._scan_exif_gps(Path(image_dir), target_name))
        else:
            # Default scan locations
            from config import PROFILES_DIR
            for default_dir in [
                PROFILES_DIR,
            ]:
                if default_dir.exists():
                    hits.extend(self._scan_exif_gps(default_dir, target_name))

        # 2. For any found coordinates, do reverse geocoding
        coord_hits = [h for h in hits if h.observable_type == "coordinates"]
        for ch in coord_hits:
            lat, lon = ch.raw_record.get("lat"), ch.raw_record.get("lon")
            if lat and lon:
                geo_hits = self._reverse_geocode(lat, lon, ch.raw_record.get("source_file", ""))
                hits.extend(geo_hits)

        return hits

    def _scan_exif_gps(self, directory: Path, target_name: str) -> list[ReconHit]:
        """Extract GPS coordinates from EXIF data in image files."""
        hits: list[ReconHit] = []
        image_extensions = {".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".png"}

        try:
            files = list(directory.rglob("*"))
        except PermissionError:
            return hits

        for fpath in files[:500]:
            if fpath.suffix.lower() not in image_extensions:
                continue
            if not fpath.is_file():
                continue

            coords = self._extract_gps_from_jpeg(fpath)
            if coords:
                lat, lon = coords
                hits.append(ReconHit(
                    observable_type="coordinates",
                    value=f"{lat:.6f},{lon:.6f}",
                    source_module=self.name,
                    source_detail=f"exif_gps:{fpath.name}",
                    confidence=0.8,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "lat": lat, "lon": lon,
                        "source_file": str(fpath),
                        "file_name": fpath.name,
                    },
                ))

        return hits

    @staticmethod
    def _extract_gps_from_jpeg(filepath: Path) -> tuple[float, float] | None:
        """
        Extract GPS coordinates from JPEG EXIF without external libraries.
        Reads raw EXIF APP1 segment and parses IFD0 → GPS IFD.
        """
        try:
            with open(filepath, "rb") as f:
                # Check JPEG SOI marker
                if f.read(2) != b'\xff\xd8':
                    return None

                # Find APP1 (EXIF) marker
                while True:
                    marker = f.read(2)
                    if len(marker) < 2:
                        return None
                    if marker == b'\xff\xe1':  # APP1
                        break
                    if marker[0:1] != b'\xff':
                        return None
                    seg_len = struct.unpack('>H', f.read(2))[0]
                    f.seek(seg_len - 2, 1)

                seg_len = struct.unpack('>H', f.read(2))[0]
                exif_data = f.read(seg_len - 2)

                # Check "Exif\x00\x00" header
                if not exif_data.startswith(b'Exif\x00\x00'):
                    return None

                tiff_data = exif_data[6:]
                if tiff_data[:2] == b'MM':
                    endian = '>'
                elif tiff_data[:2] == b'II':
                    endian = '<'
                else:
                    return None

                ifd0_offset = struct.unpack(f'{endian}I', tiff_data[4:8])[0]

                gps_offset = SatIntelAdapter._find_tag_in_ifd(
                    tiff_data, ifd0_offset, 0x8825, endian
                )
                if not gps_offset:
                    return None

                return SatIntelAdapter._parse_gps_ifd(tiff_data, gps_offset, endian)

        except (OSError, struct.error, IndexError, ValueError):
            return None

    @staticmethod
    def _find_tag_in_ifd(data: bytes, ifd_offset: int, target_tag: int, endian: str) -> int | None:
        """Find a specific tag value in an IFD."""
        try:
            num_entries = struct.unpack(f'{endian}H', data[ifd_offset:ifd_offset + 2])[0]
            for i in range(num_entries):
                entry_offset = ifd_offset + 2 + i * 12
                tag = struct.unpack(f'{endian}H', data[entry_offset:entry_offset + 2])[0]
                if tag == target_tag:
                    value = struct.unpack(f'{endian}I', data[entry_offset + 8:entry_offset + 12])[0]
                    return value
        except (struct.error, IndexError):
            pass
        return None

    @staticmethod
    def _parse_gps_ifd(data: bytes, gps_offset: int, endian: str) -> tuple[float, float] | None:
        """Parse GPS IFD entries to extract lat/lon."""
        try:
            num_entries = struct.unpack(f'{endian}H', data[gps_offset:gps_offset + 2])[0]
            gps_tags: dict[int, Any] = {}

            for i in range(num_entries):
                entry_offset = gps_offset + 2 + i * 12
                tag = struct.unpack(f'{endian}H', data[entry_offset:entry_offset + 2])[0]
                type_id = struct.unpack(f'{endian}H', data[entry_offset + 2:entry_offset + 4])[0]
                count = struct.unpack(f'{endian}I', data[entry_offset + 4:entry_offset + 8])[0]
                value_offset = struct.unpack(f'{endian}I', data[entry_offset + 8:entry_offset + 12])[0]

                if type_id == 2:  # ASCII (lat/lon ref: N/S/E/W)
                    if count <= 4:
                        val = data[entry_offset + 8:entry_offset + 8 + count].decode('ascii', errors='ignore').strip('\x00')
                    else:
                        val = data[value_offset:value_offset + count].decode('ascii', errors='ignore').strip('\x00')
                    gps_tags[tag] = val
                elif type_id == 5 and count == 3:  # RATIONAL x3 (DMS)
                    rationals = []
                    for j in range(3):
                        num = struct.unpack(f'{endian}I', data[value_offset + j * 8:value_offset + j * 8 + 4])[0]
                        den = struct.unpack(f'{endian}I', data[value_offset + j * 8 + 4:value_offset + j * 8 + 8])[0]
                        rationals.append(num / den if den else 0.0)
                    gps_tags[tag] = rationals

            lat_ref = gps_tags.get(1, "N")
            lat_dms = gps_tags.get(2)
            lon_ref = gps_tags.get(3, "E")
            lon_dms = gps_tags.get(4)

            if not lat_dms or not lon_dms:
                return None

            lat = lat_dms[0] + lat_dms[1] / 60.0 + lat_dms[2] / 3600.0
            lon = lon_dms[0] + lon_dms[1] / 60.0 + lon_dms[2] / 3600.0

            if lat_ref == "S":
                lat = -lat
            if lon_ref == "W":
                lon = -lon

            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)

        except (struct.error, IndexError, ValueError, ZeroDivisionError):
            pass
        return None

    def _reverse_geocode(self, lat: float, lon: float, source_file: str) -> list[ReconHit]:
        """Reverse geocode coordinates via Nominatim."""
        hits: list[ReconHit] = []
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16"
        status, body = self._fetch(url, headers={"Accept": "application/json"})
        if status == 200 and body:
            try:
                data = json.loads(body)
                display = data.get("display_name", "")
                if display:
                    hits.append(ReconHit(
                        observable_type="location",
                        value=display,
                        source_module=self.name,
                        source_detail=f"reverse_geocode:{lat:.4f},{lon:.4f}",
                        confidence=0.7,
                        timestamp=datetime.now().isoformat(),
                        raw_record={
                            "lat": lat, "lon": lon,
                            "address": data.get("address", {}),
                            "display_name": display,
                            "source_file": source_file,
                        },
                    ))
            except json.JSONDecodeError:
                pass
        return hits


# ── Search4Faces Adapter (Facial Recognition) ───────────────────

class Search4FacesAdapter(ReconAdapter):
    """
    Search4Faces — facial recognition pivot for VK/OK profiles.

    Takes a face image URL and searches VK and Odnoklassniki
    for matching faces, returning profile URLs.

    Requires: SEARCH4FACES_API_KEY env var
    """

    name = "search4faces"
    region = "global"

    _API_BASE = "https://search4faces.com/api/search"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []
        api_key = os.environ.get("SEARCH4FACES_API_KEY", "").strip()
        if not api_key:
            return hits

        # Collect face image URLs from known profiles
        image_urls = self._collect_face_images(target_name, known_usernames)

        for img_url in image_urls[:3]:
            hits.extend(self._search_faces(api_key, img_url, "vk", target_name))
            hits.extend(self._search_faces(api_key, img_url, "ok", target_name))
            time.sleep(1)  # rate limiting

        return hits

    def _collect_face_images(self, target_name: str, known_usernames: list[str]) -> list[str]:
        """Collect face image URLs from known profiles."""
        urls: list[str] = []
        for username in known_usernames:
            urls.append(f"https://instagram.com/{urllib.parse.quote(username, safe='')}/")
        return urls

    def _search_faces(
        self, api_key: str, image_url: str, source_db: str, target_name: str
    ) -> list[ReconHit]:
        """Call Search4Faces API to find matching faces."""
        hits: list[ReconHit] = []

        data = {
            "image_url": image_url,
            "source": source_db,
        }
        headers = {"X-Api-Key": api_key}

        status, body = self._post(self._API_BASE, data=data, headers=headers)
        if status != 200 or not body:
            return hits

        try:
            result = json.loads(body)
            faces = result.get("results", result.get("faces", []))
            for face in faces[:10]:
                profile_url = face.get("url", face.get("profile", ""))
                similarity = face.get("similarity", face.get("score", 0.0))
                full_name = face.get("name", face.get("full_name", ""))

                if not profile_url:
                    continue

                name_parts = set(target_name.lower().split())
                name_match = any(p in full_name.lower() for p in name_parts if len(p) > 2) if full_name else False

                conf = min(0.9, similarity) if isinstance(similarity, (int, float)) and similarity > 0 else 0.4
                if name_match:
                    conf = min(1.0, conf + 0.15)

                hits.append(ReconHit(
                    observable_type="url",
                    value=profile_url,
                    source_module=self.name,
                    source_detail=f"face_match:{source_db}:{similarity:.0%}" if isinstance(similarity, float) else f"face_match:{source_db}",
                    confidence=conf,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "source_db": source_db,
                        "similarity": similarity,
                        "name_found": full_name,
                        "name_match": name_match,
                        "image_url_searched": image_url,
                    },
                    cross_refs=[target_name],
                ))
        except (json.JSONDecodeError, TypeError):
            pass

        return hits


# ── Web Search Adapter (DuckDuckGo + Playwright) ────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:128.0) Gecko/20100101 Firefox/128.0",
]

# Patterns for classifying result URLs
_PLATFORM_PATTERNS: list[tuple[re.Pattern[str], str, str, float]] = [
    (re.compile(r"linkedin\.com/in/([^/?#]+)", re.I), "username", "linkedin_profile", 0.7),
    (re.compile(r"linkedin\.com/company/([^/?#]+)", re.I), "url", "linkedin_company", 0.6),
    (re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?$", re.I), "username", "instagram_profile", 0.7),
    (re.compile(r"facebook\.com/([A-Za-z0-9_.]+)/?$", re.I), "url", "facebook_profile", 0.65),
    (re.compile(r"vk\.com/([A-Za-z0-9_.]+)/?$", re.I), "username", "vk_profile", 0.65),
    (re.compile(r"ok\.ru/profile/(\d+)", re.I), "url", "ok_profile", 0.6),
    (re.compile(r"twitter\.com/([A-Za-z0-9_]+)/?$", re.I), "username", "twitter_profile", 0.65),
    (re.compile(r"x\.com/([A-Za-z0-9_]+)/?$", re.I), "username", "twitter_profile", 0.65),
    (re.compile(r"t\.me/([A-Za-z0-9_]+)/?$", re.I), "username", "telegram_channel", 0.65),
    (re.compile(r"scholar\.google\.", re.I), "url", "academic_scholar", 0.6),
    (re.compile(r"researchgate\.net/profile/", re.I), "url", "academic_researchgate", 0.6),
    (re.compile(r"\.edu/", re.I), "url", "academic_university", 0.55),
    (re.compile(r"youtube\.com/(c/|channel/|@)([^/?#]+)", re.I), "url", "youtube_channel", 0.55),
]


class WebSearchAdapter(ReconAdapter):
    """
    Web search adapter — DuckDuckGo queries + Playwright page scraping.

    Performs targeted searches for name/phone/usernames across DuckDuckGo,
    scrapes top results with Playwright for JS-rendered pages, and
    classifies results into social/academic/professional profiles.

    No API keys required. Uses public DuckDuckGo HTML search.
    """

    name = "web_search"
    region = "global"

    _DDG_URL = "https://html.duckduckgo.com/html/"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        import random

        hits: list[ReconHit] = []
        seen_urls: set[str] = set()

        queries = self._build_queries(target_name, known_phones, known_usernames)

        browser = None
        pw_context = None
        try:
            from playwright.sync_api import sync_playwright
            pw_context = sync_playwright().start()
            browser = pw_context.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            log.warning("Playwright unavailable, falling back to static scraping: %s", exc)

        try:
            for query in queries:
                delay = random.uniform(2.0, 5.0)
                time.sleep(delay)

                results = self._ddg_search(query)
                for r in results:
                    url = r.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = r.get("title", "")
                    snippet = r.get("snippet", "")

                    # Scrape page for richer metadata if browser available
                    page_meta: dict[str, Any] = {}
                    if browser and self._should_scrape(url):
                        page_meta = self._scrape_page(browser, url)

                    hit = self._classify_url(
                        url, title, snippet, page_meta, query, target_name,
                    )
                    if hit:
                        hits.append(hit)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw_context:
                try:
                    pw_context.stop()
                except Exception:
                    pass

        return hits

    # ── Query builder ──

    def _build_queries(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[str]:
        queries: list[str] = []
        name = target_name.strip()
        if name:
            queries.append(f'"{name}"')
            queries.append(f'"{name}" site:linkedin.com')
            queries.append(f'"{name}" site:instagram.com')
            queries.append(f'"{name}" site:facebook.com')
            queries.append(f'"{name}" site:vk.com')
            queries.append(f'"{name}" site:scholar.google.com OR site:researchgate.net')
        for phone in known_phones[:3]:
            queries.append(f'"{phone}" -spam -lookup -reverse')
        for uname in known_usernames[:3]:
            if uname.strip().lower() != name.lower():
                queries.append(f'"{uname}"')
        return queries

    # ── DuckDuckGo HTML search ──

    def _ddg_search(self, query: str, max_results: int = 15) -> list[dict[str, str]]:
        import random

        ua = random.choice(_USER_AGENTS)
        data = urllib.parse.urlencode({"q": query, "kl": ""}).encode("utf-8")
        req = urllib.request.Request(
            self._DDG_URL,
            data=data,
            headers={"User-Agent": ua, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            if self._opener:
                resp = self._opener.open(req, timeout=self.timeout)
            else:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
            body = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, OSError) as exc:
            log.warning("DuckDuckGo search failed for %r: %s", query, exc)
            return []

        return self._parse_ddg_html(body, max_results)

    def _parse_ddg_html(self, html_text: str, max_results: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        # DuckDuckGo HTML results: <a class="result__a" href="...">title</a>
        # and <a class="result__snippet" ...>snippet</a>
        # Use regex to extract — no external HTML parser dependency
        blocks = re.findall(
            r'<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        snippets = re.findall(
            r'<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        for i, (raw_url, raw_title) in enumerate(blocks[:max_results]):
            # DDG wraps URLs through redirects — extract actual URL
            url = self._extract_ddg_url(raw_url)
            if not url:
                continue
            title = re.sub(r"<[^>]+>", "", raw_title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
            results.append({"url": url, "title": title, "snippet": snippet})
        return results

    @staticmethod
    def _extract_ddg_url(raw: str) -> str:
        """Extract actual URL from DuckDuckGo redirect wrapper."""
        raw = raw.strip()
        if raw.startswith("//duckduckgo.com/l/?"):
            parsed = urllib.parse.urlparse("https:" + raw)
            params = urllib.parse.parse_qs(parsed.query)
            uddg = params.get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        if raw.startswith("http"):
            return raw
        return ""

    # ── Playwright page scraper ──

    @staticmethod
    def _should_scrape(url: str) -> bool:
        """Only scrape domains that benefit from JS rendering."""
        js_domains = (
            "linkedin.com", "instagram.com", "facebook.com",
            "vk.com", "twitter.com", "x.com",
        )
        return any(d in url.lower() for d in js_domains)

    @staticmethod
    def _scrape_page(browser: Any, url: str) -> dict[str, Any]:
        """Scrape a page with Playwright headless Chromium."""
        import random

        meta: dict[str, Any] = {}
        context = None
        try:
            context = browser.new_context(
                viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
                user_agent=random.choice(_USER_AGENTS),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(random.uniform(0.5, 1.5))

            meta["title"] = page.title() or ""

            # Meta description
            desc_el = page.query_selector('meta[name="description"]')
            meta["description"] = desc_el.get_attribute("content") if desc_el else ""

            # Open Graph tags
            og_tags: dict[str, str] = {}
            for og_el in page.query_selector_all('meta[property^="og:"]'):
                prop = og_el.get_attribute("property") or ""
                content = og_el.get_attribute("content") or ""
                if prop and content:
                    og_tags[prop] = content
            meta["og"] = og_tags

            # JSON-LD structured data
            ld_scripts = page.query_selector_all('script[type="application/ld+json"]')
            ld_data: list[Any] = []
            for script in ld_scripts[:3]:
                try:
                    ld_data.append(json.loads(script.inner_text()))
                except (json.JSONDecodeError, Exception):
                    pass
            meta["json_ld"] = ld_data

            # Text snippet (first 2000 chars of visible text)
            body_text = page.inner_text("body") or ""
            meta["text_snippet"] = body_text[:2000]

        except Exception as exc:
            log.debug("Playwright scrape failed for %s: %s", url, exc)
            meta["error"] = str(exc)
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
        return meta

    # ── URL classifier ──

    def _classify_url(
        self,
        url: str,
        title: str,
        snippet: str,
        page_meta: dict[str, Any],
        query: str,
        target_name: str,
    ) -> ReconHit | None:
        """Classify a search result URL into a typed ReconHit."""
        obs_type = "url"
        source_detail = "web_mention"
        confidence = 0.5
        value = url

        for pattern, ptype, pdetail, pconf in _PLATFORM_PATTERNS:
            m = pattern.search(url)
            if m:
                obs_type = ptype
                source_detail = pdetail
                confidence = pconf
                if ptype == "username" and m.lastindex and m.lastindex >= 1:
                    value = m.group(1)
                break

        # Boost confidence if target name appears in title/snippet
        name_parts = [p.lower() for p in target_name.split() if len(p) > 2]
        combined_text = f"{title} {snippet} {page_meta.get('description', '')} {page_meta.get('text_snippet', '')}".lower()
        name_matches = sum(1 for p in name_parts if p in combined_text)
        if name_parts and name_matches >= len(name_parts):
            confidence = min(1.0, confidence + 0.1)
        elif name_matches == 0:
            confidence = max(0.2, confidence - 0.15)

        raw_record: dict[str, Any] = {
            "url": url,
            "title": title,
            "snippet": snippet,
            "query": query,
        }
        if page_meta:
            raw_record["page_title"] = page_meta.get("title", "")
            raw_record["page_description"] = page_meta.get("description", "")
            raw_record["og"] = page_meta.get("og", {})
            raw_record["json_ld"] = page_meta.get("json_ld", [])

        return ReconHit(
            observable_type=obs_type,
            value=value,
            source_module=self.name,
            source_detail=source_detail,
            confidence=round(confidence, 2),
            timestamp=datetime.now().isoformat(),
            raw_record=raw_record,
            cross_refs=[target_name],
        )


# ── OpenDataBot UA Business Registry Adapter ─────────────────────

class OpenDataBotAdapter(ReconAdapter):
    """
    Ukrainian business-registry (ЄДР) deanonymisation adapter.

    Links a person's name/phone to registered businesses (ТОВ) and
    sole proprietors (ФОП) via OpenDataBot, returning legal name,
    ЄДРПОУ/ІПН, registered address, role (CEO/founder/beneficiary),
    activities, and registration status.

    Dual strategy:
      1. **Web search** — scrape opendatabot.ua/search?q=Name (no key)
      2. **API enrich** — /company/{code}, /fop/{code}, /person/{code}
         for full data when OPENDATABOT_API_KEY is set

    Phone cross-match against known_phones yields near-certain deanon.

    Env vars
    --------
    OPENDATABOT_API_KEY  — API key (optional, free trial available)
    """

    name = "opendatabot"
    region = "ua"

    _SEARCH_URL = "https://opendatabot.ua/"
    _API_BASE = "https://opendatabot.com/api/v4"

    # ── entry-point ──

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        api_key = os.environ.get("OPENDATABOT_API_KEY", "").strip()
        hits: list[ReconHit] = []

        # Strategy 1: web scrape for name ──────────────────────
        entities = self._web_search(target_name)

        # Strategy 2: API enrichment of found entities ─────────
        for ent in entities:
            code = ent.get("code", "")
            if api_key and code:
                enriched = self._api_lookup(code, ent.get("entity_type", "company"), api_key)
                if enriched:
                    ent.update(enriched)

            hit = self._entity_to_hit(ent, target_name, known_phones)
            if hit:
                hits.append(hit)

        # Strategy 3: API person lookup for name variants ──────
        if api_key:
            # Try Cyrillic transliterations as person search
            for ipn in self._extract_ipn_from_hits(hits):
                person_hits = self._api_person_roles(ipn, target_name, api_key)
                hits.extend(person_hits)

        return self._dedup_by_code(hits)

    # ── web scrape ──

    def _web_search(self, query: str) -> list[dict[str, Any]]:
        """Scrape opendatabot.ua for companies/FOPs matching query.

        OpenDataBot is a Nuxt.js SPA — plain HTTP returns an empty shell.
        Strategy: Playwright first → DDG site-search fallback → static fetch.
        """
        encoded = urllib.parse.quote(query)
        url = f"{self._SEARCH_URL}?q={encoded}"

        body = ""
        # Strategy A: Playwright (renders JS SPA)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(2000)  # give Vue/Nuxt hydration time
                body = page.content()
                browser.close()
        except Exception:
            pass

        entities = self._parse_search_html(body, query) if body else []

        # Strategy B: DuckDuckGo site-search fallback (no JS needed)
        if not entities:
            entities = self._ddg_site_search(query)

        return entities

    def _ddg_site_search(self, query: str) -> list[dict[str, Any]]:
        """Search DDG for 'site:opendatabot.ua "name"' and extract codes from URLs."""
        encoded = urllib.parse.quote(f'site:opendatabot.ua "{query}"')
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status != 200 or not body:
            return []

        entities: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Extract opendatabot URLs from DDG snippets
        for m in re.finditer(r'opendatabot\.ua/c/(\d{5,10})', body):
            code = m.group(1)
            if code not in seen:
                seen.add(code)
                entities.append({"code": code, "name": query, "entity_type": "company", "source": "ddg_site_search"})

        for m in re.finditer(r'opendatabot\.ua/fop/(\d{8,10})', body):
            code = m.group(1)
            if code not in seen:
                seen.add(code)
                entities.append({"code": code, "name": query, "entity_type": "fop", "source": "ddg_site_search"})

        for m in re.finditer(r'opendatabot\.ua/p/([a-z0-9\-]{5,80})', body, re.IGNORECASE):
            slug = m.group(1)
            if slug not in seen:
                seen.add(slug)
                entities.append({"code": slug, "name": query, "entity_type": "person", "source": "ddg_site_search"})

        return entities[:20]

    def _parse_search_html(self, html: str, query: str) -> list[dict[str, Any]]:
        """
        Extract entity cards from OpenDataBot search results HTML.
        Looks for company/FOP links: /c/{code} for companies, /fop/{code} for FOPs.
        """
        entities: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        # Pattern 1: company links /c/{ЄДРПОУ}
        for m in re.finditer(
            r'href="/c/(\d{5,10})"[^>]*>([^<]{3,120})</a>',
            html,
        ):
            code, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if code not in seen_codes and name:
                seen_codes.add(code)
                entities.append({
                    "code": code, "name": name,
                    "entity_type": "company", "source": "web_search",
                })

        # Pattern 2: FOP links /fop/{ІПН}
        for m in re.finditer(
            r'href="/fop/(\d{8,10})"[^>]*>([^<]{3,120})</a>',
            html,
        ):
            code, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if code not in seen_codes and name:
                seen_codes.add(code)
                entities.append({
                    "code": code, "name": name,
                    "entity_type": "fop", "source": "web_search",
                })

        # Pattern 3: person profile links /p/{slug} (Nuxt SPA rendered)
        for m in re.finditer(
            r'href="/p/([a-z0-9\-]{5,80})"[^>]*>([^<]{3,120})</a>',
            html, re.IGNORECASE,
        ):
            slug, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if slug not in seen_codes and name:
                seen_codes.add(slug)
                entities.append({
                    "code": slug, "name": name,
                    "entity_type": "person", "source": "web_search",
                })

        return entities[:20]

    # ── API methods ──

    def _api_lookup(self, code: str, entity_type: str, api_key: str) -> dict[str, Any]:
        """Fetch full registration data for a company or FOP."""
        if entity_type == "fop":
            endpoint = f"{self._API_BASE}/fop/{code}"
        else:
            endpoint = f"{self._API_BASE}/company/{code}"

        status, body = self._fetch(
            f"{endpoint}?apiKey={api_key}",
            headers={"Accept": "application/json"},
        )
        if status != 200 or not body:
            return {}
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {}

        usr = data.get("USR", {})
        result: dict[str, Any] = {}

        if entity_type == "fop":
            result["full_name"] = usr.get("fullName") or data.get("fullName", "")
            result["address"] = usr.get("location", "")
            result["status"] = usr.get("status", "")
            result["registration_date"] = usr.get("registrationDate", "")
            result["birth_date"] = usr.get("birthDate", "")
            result["primary_activity"] = usr.get("primaryActivity", "")
            result["phones"] = usr.get("phones", [])
            result["email"] = usr.get("email", "")
        else:
            result["full_name"] = usr.get("fullName") or data.get("companyName", "")
            result["short_name"] = usr.get("shortName", "")
            result["ceo"] = usr.get("ceoName", "")
            result["address"] = usr.get("location", "")
            result["status"] = usr.get("status", "")
            result["registration_date"] = usr.get("registrationDate", "")
            result["primary_activity"] = usr.get("primaryActivity", "")
            result["capital"] = usr.get("capital", 0)
            result["phones"] = usr.get("phones", [])
            result["heads"] = [
                {"name": h.get("name", ""), "role": h.get("role", "")}
                for h in usr.get("heads", [])
            ]
            result["beneficiaries"] = [
                {"name": b.get("name", ""), "role": b.get("role", "")}
                for b in usr.get("beneficiaries", [])
            ]

        return result

    def _api_person_roles(
        self, ipn: str, target_name: str, api_key: str,
    ) -> list[ReconHit]:
        """Fetch all business roles for a person by ІПН."""
        url = f"{self._API_BASE}/person/{ipn}?apiKey={api_key}"
        status, body = self._fetch(url, headers={"Accept": "application/json"})
        if status != 200 or not body:
            return []
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []

        hits: list[ReconHit] = []
        usr_roles = data.get("USRRoles", {})

        for role_type in ("ceo", "founder", "fop", "beneficiary", "assignee"):
            items = usr_roles.get(role_type, [])
            if not isinstance(items, list):
                continue
            for item in items[:10]:
                company_code = item.get("code", "")
                company_name = item.get("name", "")
                state_text = item.get("stateText", "")
                if not company_code:
                    continue
                hits.append(ReconHit(
                    observable_type="business_role",
                    value=f"{role_type}@{company_code}",
                    source_module=self.name,
                    source_detail=f"person_roles:{role_type}",
                    confidence=0.85,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "ipn": ipn, "role": role_type,
                        "company_code": company_code,
                        "company_name": company_name,
                        "state": state_text,
                    },
                    cross_refs=[target_name, ipn],
                ))
        return hits

    # ── hit conversion ──

    def _entity_to_hit(
        self, ent: dict[str, Any], target_name: str,
        known_phones: list[str],
    ) -> ReconHit | None:
        code = ent.get("code", "")
        name = ent.get("name", "") or ent.get("full_name", "")
        if not code or not name:
            return None

        entity_type = ent.get("entity_type", "company")
        confidence = 0.6
        source_detail = f"edr_{entity_type}"

        # Name match scoring — try both original and Cyrillic transliterations
        name_parts = {p.lower() for p in target_name.split() if len(p) > 2}
        cyrillic_parts: set[str] = set()
        for variant in _transliterate_to_cyrillic(target_name):
            cyrillic_parts.update(p.lower() for p in variant.split() if len(p) > 2)
        all_parts = name_parts | cyrillic_parts
        entity_name_lower = name.lower()
        ceo_name = ent.get("ceo", "").lower()
        combined = f"{entity_name_lower} {ceo_name}"
        name_matches = sum(1 for p in all_parts if p in combined)

        if name_parts and name_matches >= len(name_parts):
            confidence = 0.8   # full name match
        elif name_matches > 0:
            confidence = 0.65  # partial match
        else:
            confidence = 0.45  # code found but name mismatch

        # Phone cross-match — near-certain deanon
        entity_phones = self._normalize_phones(ent.get("phones", []))
        known_norm = self._normalize_phones(known_phones)
        phone_overlap = entity_phones & known_norm
        if phone_overlap:
            confidence = 0.95
            source_detail = f"edr_{entity_type}:phone_match"

        raw_record: dict[str, Any] = {
            "code": code,
            "entity_type": entity_type,
            "name": name,
            "address": ent.get("address", ""),
            "status": ent.get("status", ""),
            "registration_date": ent.get("registration_date", ""),
            "primary_activity": ent.get("primary_activity", ""),
            "source": ent.get("source", ""),
        }
        if entity_type == "company":
            raw_record["ceo"] = ent.get("ceo", "")
            raw_record["capital"] = ent.get("capital", 0)
            raw_record["heads"] = ent.get("heads", [])
            raw_record["beneficiaries"] = ent.get("beneficiaries", [])
        if phone_overlap:
            raw_record["matched_phones"] = list(phone_overlap)
        if ent.get("phones"):
            raw_record["phones"] = ent["phones"]

        return ReconHit(
            observable_type="business_entity",
            value=f"{entity_type}:{code}",
            source_module=self.name,
            source_detail=source_detail,
            confidence=round(confidence, 2),
            timestamp=datetime.now().isoformat(),
            raw_record=raw_record,
            cross_refs=[target_name] + list(phone_overlap),
        )

    # ── helpers ──

    @staticmethod
    def _normalize_phones(phones: list[str]) -> set[str]:
        """Strip non-digit chars and normalize to last 10 digits."""
        out: set[str] = set()
        for p in phones:
            digits = re.sub(r"\D", "", str(p))
            if len(digits) >= 10:
                out.add(digits[-10:])
        return out

    @staticmethod
    def _extract_ipn_from_hits(hits: list[ReconHit]) -> list[str]:
        """Pull any ІПН-like codes from FOP hits."""
        ipns: list[str] = []
        for h in hits:
            code = h.raw_record.get("code", "")
            if h.raw_record.get("entity_type") == "fop" and len(code) == 10:
                ipns.append(code)
        return ipns[:5]

    @staticmethod
    def _dedup_by_code(hits: list[ReconHit]) -> list[ReconHit]:
        """Keep highest-confidence hit per business code."""
        best: dict[str, ReconHit] = {}
        for h in hits:
            code = h.raw_record.get("code") or h.raw_record.get("company_code") or h.value
            existing = best.get(code)
            if not existing or h.confidence > existing.confidence:
                best[code] = h
        return list(best.values())


# ── NASA FIRMS Thermal Anomaly Adapter ───────────────────────────

class FIRMSAdapter(ReconAdapter):
    """
    NASA FIRMS thermal-anomaly corroboration adapter.

    Queries FIRMS (Fire Information for Resource Management System) for
    satellite-detected thermal anomalies in a bounding box around known
    coordinates.  Coordinate sources (checked in order):
      1. FIRMS_LAT / FIRMS_LON env vars (manual override)
      2. STIX 2.1 *location* objects in recent Drop-Zone bundles

    Returns ReconHit(observable_type="thermal_anomaly") with raw FRP,
    brightness, sensor confidence, distance-from-origin, and satellite
    metadata.

    Env vars
    --------
    FIRMS_MAP_KEY    — NASA FIRMS API key  (required, free from NASA)
    FIRMS_LAT        — centre latitude     (optional)
    FIRMS_LON        — centre longitude    (optional)
    FIRMS_RADIUS_KM  — search radius, km   (default 25)
    HANNA_DROP_ZONE  — path to drop zone   (for STIX coordinate scan)
    """

    name = "firms"
    region = "global"

    _BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    _SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT")
    _KM_TO_DEG = 1.0 / 111.0  # approx at equator

    # ── search entry-point ──

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        map_key = os.environ.get("FIRMS_MAP_KEY", "")
        if not map_key:
            log.warning("FIRMS: FIRMS_MAP_KEY not set — skipping")
            return []

        coords = self._gather_coordinates()
        if not coords:
            log.info("FIRMS: no coordinates available for corroboration")
            return []

        hits: list[ReconHit] = []
        for lat, lon, origin in coords:
            bbox = self._bbox(lat, lon)
            for src in self._SOURCES:
                for row in self._query(map_key, src, bbox):
                    hit = self._row_to_hit(row, lat, lon, src, origin, target_name)
                    if hit:
                        hits.append(hit)
        return self._dedup(hits)

    # ── coordinate gathering ──

    def _gather_coordinates(self) -> list[tuple[float, float, str]]:
        coords: list[tuple[float, float, str]] = []
        lat_s = os.environ.get("FIRMS_LAT", "")
        lon_s = os.environ.get("FIRMS_LON", "")
        if lat_s and lon_s:
            try:
                coords.append((float(lat_s), float(lon_s), "env_override"))
            except ValueError:
                pass

        dz = os.environ.get("HANNA_DROP_ZONE", "")
        if dz:
            coords.extend(self._scan_drop_zone(Path(dz)))
        return coords[:10]

    def _scan_drop_zone(self, dz: Path) -> list[tuple[float, float, str]]:
        if not dz.is_dir():
            return []
        cutoff = datetime.now() - timedelta(hours=6)
        out: list[tuple[float, float, str]] = []
        for rpt in sorted(dz.glob("*/report.json"), reverse=True)[:20]:
            try:
                if datetime.fromtimestamp(rpt.stat().st_mtime) < cutoff:
                    continue
                with open(rpt, encoding="utf-8") as f:
                    bundle = json.load(f)
                for obj in bundle.get("objects", []):
                    if obj.get("type") == "location":
                        lat = obj.get("latitude")
                        lon = obj.get("longitude")
                        if lat is not None and lon is not None:
                            out.append((float(lat), float(lon),
                                        f"stix:{rpt.parent.name}"))
            except (json.JSONDecodeError, OSError, ValueError, KeyError):
                continue
        return out

    # ── FIRMS HTTP layer ──

    def _bbox(self, lat: float, lon: float) -> str:
        r = float(os.environ.get("FIRMS_RADIUS_KM", "25")) * self._KM_TO_DEG
        w = max(-180.0, lon - r)
        s = max(-90.0, lat - r)
        e = min(180.0, lon + r)
        n = min(90.0, lat + r)
        return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"

    def _query(self, key: str, source: str, bbox: str,
              day_range: int = 2) -> list[dict[str, str]]:
        url = f"{self._BASE}/{key}/{source}/{bbox}/{day_range}"
        status, body = self._fetch(url)
        if status != 200 or not body or body.lstrip().startswith("<"):
            return []
        return self._parse_csv(body)

    @staticmethod
    def _parse_csv(text: str) -> list[dict[str, str]]:
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return []
        hdr = [h.strip() for h in lines[0].split(",")]
        rows: list[dict[str, str]] = []
        for ln in lines[1:]:
            vals = ln.split(",")
            if len(vals) == len(hdr):
                rows.append(dict(zip(hdr, (v.strip() for v in vals))))
        return rows

    # ── Hit conversion ──

    def _row_to_hit(
        self, row: dict, o_lat: float, o_lon: float,
        source: str, origin: str, target_name: str,
    ) -> ReconHit | None:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError, TypeError):
            return None

        dist = self._haversine(o_lat, o_lon, lat, lon)
        frp = self._safe_float(row.get("frp", "0"))

        # sensor confidence
        raw_c = row.get("confidence", "")
        if raw_c in ("h", "high"):
            sc = 0.9
        elif raw_c in ("n", "nominal"):
            sc = 0.7
        elif raw_c in ("l", "low"):
            sc = 0.4
        else:
            sc = min(1.0, self._safe_float(raw_c) / 100) if raw_c else 0.5

        radius = float(os.environ.get("FIRMS_RADIUS_KM", "25"))
        dist_decay = max(0.3, 1.0 - dist / radius)
        frp_bonus = min(0.15, frp / 200)
        conf = round(min(1.0, dist_decay * sc + frp_bonus), 2)

        return ReconHit(
            observable_type="thermal_anomaly",
            value=f"{lat:.5f},{lon:.5f}",
            source_module=self.name,
            source_detail=f"firms_{source.lower()}",
            confidence=conf,
            timestamp=datetime.now().isoformat(),
            raw_record={
                "latitude": lat, "longitude": lon,
                "frp": frp,
                "brightness": row.get("bright_ti4") or row.get("brightness") or "",
                "sensor_confidence": raw_c,
                "acq_date": row.get("acq_date", ""),
                "acq_time": row.get("acq_time", ""),
                "daynight": row.get("daynight", ""),
                "satellite": row.get("satellite", ""),
                "source": source,
                "distance_km": round(dist, 2),
                "origin_lat": o_lat, "origin_lon": o_lon,
                "origin_label": origin,
            },
            cross_refs=[target_name, origin],
        )

    # ── helpers ──

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _safe_float(v: str, default: float = 0.0) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def _dedup(self, hits: list[ReconHit], min_km: float = 0.5) -> list[ReconHit]:
        if not hits:
            return hits
        kept = [hits[0]]
        for h in hits[1:]:
            lat2 = h.raw_record.get("latitude", 0)
            lon2 = h.raw_record.get("longitude", 0)
            replaced = False
            for i, k in enumerate(kept):
                d = self._haversine(
                    k.raw_record.get("latitude", 0),
                    k.raw_record.get("longitude", 0),
                    lat2, lon2,
                )
                if d < min_km:
                    if h.confidence > k.confidence:
                        kept[i] = h
                    replaced = True
                    break
            if not replaced:
                kept.append(h)
        return kept


# ── Transliteration helpers ──────────────────────────────────────

_LATIN_TO_CYR = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д",
    "e": "е", "zh": "ж", "z": "з", "i": "і", "y": "й",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "r": "р", "s": "с", "t": "т", "u": "у",
    "f": "ф", "kh": "х", "ts": "ц", "ch": "ч", "sh": "ш",
    "shch": "щ", "yu": "ю", "ya": "я", "h": "г",
    "nn": "нн",
}

# Common UA name transliteration variants
_NAME_VARIANTS = {
    "hanna": ["ганна", "ханна", "анна"],
    "anna": ["анна", "ганна"],
    "dosenko": ["досенко", "дозенко"],
}


def _transliterate_to_cyrillic(latin_name: str) -> list[str]:
    """Generate Cyrillic variants of a Latin name for leak searching."""
    results = []
    parts = latin_name.lower().split()

    # Check known name variants first
    cyrillic_parts_options: list[list[str]] = []
    for part in parts:
        if part in _NAME_VARIANTS:
            cyrillic_parts_options.append(_NAME_VARIANTS[part])
        else:
            # Simple character-by-character transliteration
            cyr = _simple_transliterate(part)
            cyrillic_parts_options.append([cyr] if cyr else [part])

    # Generate combinations (cap at 6 to avoid explosion)
    if len(cyrillic_parts_options) == 2:
        for first in cyrillic_parts_options[0]:
            for last in cyrillic_parts_options[1]:
                results.append(f"{first.capitalize()} {last.capitalize()}")
                if len(results) >= 6:
                    return results
    elif len(cyrillic_parts_options) == 1:
        results = [v.capitalize() for v in cyrillic_parts_options[0]]
    else:
        # Fallback: simple transliterate the full name
        cyr = _simple_transliterate(latin_name)
        if cyr:
            results.append(cyr)

    return results[:6]


def _simple_transliterate(text: str) -> str:
    """Simple Latin → Cyrillic transliteration."""
    result = []
    i = 0
    text_lower = text.lower()
    while i < len(text_lower):
        # Try multi-char mappings first (shch, sh, ch, zh, kh, ts, yu, ya)
        matched = False
        for length in (4, 3, 2):
            chunk = text_lower[i:i + length]
            if chunk in _LATIN_TO_CYR:
                result.append(_LATIN_TO_CYR[chunk])
                i += length
                matched = True
                break
        if not matched:
            ch = text_lower[i]
            if ch in _LATIN_TO_CYR:
                result.append(_LATIN_TO_CYR[ch])
            else:
                result.append(ch)
            i += 1
    return "".join(result)


# ── Module registry ──────────────────────────────────────────────

MODULES: dict[str, type[ReconAdapter]] = {
    "ua_leak": UALeakAdapter,
    "ru_leak": RULeakAdapter,
    "vk_graph": VKGraphAdapter,
    "avito": AvitoAdapter,
    "ua_phone": UAPhoneAdapter,
    "maryam": MaryamAdapter,
    "ashok": AshokAdapter,
    "ghunt": GHuntAdapter,
    "social_analyzer": SocialAnalyzerAdapter,
    "satintel": SatIntelAdapter,
    "search4faces": Search4FacesAdapter,
    "web_search": WebSearchAdapter,
    "firms": FIRMSAdapter,
    "opendatabot": OpenDataBotAdapter,
}

# Presets
MODULE_PRESETS: dict[str, list[str]] = {
    "deep-ua": ["ua_leak", "ua_phone", "opendatabot"],
    "deep-ru": ["ru_leak", "vk_graph", "avito"],
    "deep-all": ["ua_leak", "ua_phone", "ru_leak", "vk_graph", "avito"],
    "leaks_all": ["ua_leak", "ru_leak"],
    # Phase 7: Military-Grade OSINT presets
    "milint": ["maryam", "ashok", "ghunt", "social_analyzer", "satintel", "search4faces", "opendatabot"],
    "infra": ["ashok", "maryam"],
    "geoint": ["satintel", "firms"],
    "social-deep": ["social_analyzer", "search4faces", "ghunt"],
    "fast-lane": ["ua_phone", "ua_leak", "ru_leak", "ghunt", "satintel", "avito", "maryam", "search4faces", "opendatabot"],
    "slow-lane": ["ashok", "vk_graph", "social_analyzer", "web_search", "firms"],
    "full-spectrum": [
        "ua_leak", "ua_phone", "ru_leak", "vk_graph", "avito",
        "maryam", "ashok", "ghunt", "social_analyzer", "satintel", "search4faces",
        "web_search", "firms", "opendatabot",
    ],
}

# ── Priority matrix (ROI-based) ──────────────────────────────────
# P0=Critical (target infrastructure), P1=High (regional leaks),
# P2=Medium (social deep dive), P3=Low (broad search)
MODULE_PRIORITY: dict[str, int] = {
    "ashok":            0,  # P0 — target website infrastructure, CMS, Wayback
    "ua_leak":          1,  # P1 — regional leaks, high hit rate
    "ua_phone":         1,  # P1 — phone resolution
    "ru_leak":          1,  # P1 — regional leaks
    "vk_graph":         2,  # P2 — social graph, moderate noise
    "avito":            2,  # P2 — marketplace
    "ghunt":            2,  # P2 — Google account pivot
    "satintel":         2,  # P2 — EXIF / GEOINT
    "search4faces":     2,  # P2 — face recognition
    "social_analyzer":  3,  # P3 — 1000+ networks, high noise
    "maryam":           3,  # P3 — broad DDG dorking
    "web_search":       1,  # P1 — DuckDuckGo + Playwright scrape
    "firms":            1,  # P1 — NASA satellite thermal corroboration
    "opendatabot":      1,  # P1 — UA business registry deanon
}

MODULE_LANE: dict[str, str] = {
    "ua_phone": "fast",
    "ua_leak": "fast",
    "ru_leak": "fast",
    "ghunt": "fast",
    "satintel": "fast",
    "avito": "fast",
    "maryam": "fast",
    "search4faces": "fast",
    "ashok": "slow",
    "vk_graph": "slow",
    "social_analyzer": "slow",
    "web_search": "slow",
    "firms": "slow",
    "opendatabot": "fast",
}
LANE_ORDER = {"fast": 0, "slow": 1}


def _kill_process_group(exc: subprocess.TimeoutExpired) -> None:
    """Kill the entire process group spawned by a timed-out subprocess."""
    try:
        pid = getattr(exc, 'pid', None)
        if pid:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


@dataclass
class ReconTask:
    """Atomic unit of work for the worker pool."""
    module_name: str
    priority: int
    adapter_cls: type[ReconAdapter]
    target_name: str
    known_phones: list[str]
    known_usernames: list[str]
    lane: str
    proxy: str | None
    timeout: float
    worker_timeout: float
    leak_dir: str | None

    def __lt__(self, other: ReconTask) -> bool:
        return (LANE_ORDER.get(self.lane, 99), self.priority) < (LANE_ORDER.get(other.lane, 99), other.priority)


@dataclass
class TaskResult:
    """Result from a single adapter execution."""
    module_name: str
    lane: str
    hits: list[ReconHit]
    error: str | None
    elapsed_sec: float
    raw_log_path: str  # path to the raw task log


# ── Worker function (runs in separate process) ──────────────────

def _run_adapter_isolated(
    adapter_cls_name: str,
    region: str,
    proxy: str | None,
    timeout: float,
    leak_dir: str | None,
    target_name: str,
    known_phones: list[str],
    known_usernames: list[str],
    log_dir: str,
) -> dict:
    """
    Execute a single adapter in an isolated worker.
    Returns a plain dict (must be picklable for ProcessPoolExecutor).
    """
    import traceback
    t0 = time.monotonic()
    mod_name = adapter_cls_name
    # Re-resolve class inside worker (ProcessPool can't pickle classes)
    adapter_cls = MODULES.get(mod_name)
    if not adapter_cls:
        return {"module": mod_name, "hits": [], "error": f"Unknown module: {mod_name}", "elapsed": 0.0, "log_path": ""}

    log_path = str(Path(log_dir) / f"task_{mod_name}_{datetime.now().strftime('%H%M%S')}.log")
    lines: list[str] = [f"[{mod_name}] START  region={region}  {datetime.now().isoformat()}\n"]

    try:
        # Cap adapter-internal timeout so slow HTTP targets don't stall the worker
        capped_timeout = min(timeout, ADAPTER_REQ_CAP)
        adapter = adapter_cls(proxy=proxy, timeout=capped_timeout, leak_dir=leak_dir)
        hits = adapter.search(target_name, known_phones, known_usernames)
        elapsed = time.monotonic() - t0
        for h in hits:
            lines.append(f"  HIT {h.observable_type}:{h.value}  conf={h.confidence:.2f}  src={h.source_detail}\n")
        lines.append(f"[{mod_name}] DONE   {len(hits)} hit(s)  {elapsed:.1f}s\n")
        # Serialize hits to dicts (picklable)
        hit_dicts = [h.to_dict() for h in hits]
        result = {"module": mod_name, "hits": hit_dicts, "error": None, "elapsed": elapsed, "log_path": log_path}
    except Exception as exc:
        elapsed = time.monotonic() - t0
        lines.append(f"[{mod_name}] ERROR  {exc}\n")
        lines.append(traceback.format_exc())
        result = {"module": mod_name, "hits": [], "error": str(exc), "elapsed": elapsed, "log_path": log_path}

    # Write atomic log file (Chain of Custody)
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("".join(lines), encoding="utf-8")
    except OSError:
        pass

    return result


# ── Runner ───────────────────────────────────────────────────────

class DeepReconRunner:
    """
    Event-Driven OSINT orchestrator with priority-based worker pool.

    Architecture (v3.0):
      - Priority matrix: P0 (infrastructure) → P3 (broad search)
      - Worker isolation: each adapter runs in a separate process
      - Atomic logging: every task writes a raw log file (Chain of Custody)
      - Graceful degradation: if one adapter hangs/crashes, others continue

    Usage:
        runner = DeepReconRunner(proxy="socks5h://127.0.0.1:9050")
        report = runner.run(
            target_name="Hanna Dosenko",
            known_phones=["+380507133698"],
            known_usernames=["hannadosenko"],
            modules=["ua_leak", "ru_leak", "vk_graph"],
        )
    """

    def __init__(
        self,
        proxy: str | None = None,
        timeout: float = 10.0,
        leak_dir: str | None = None,
        max_workers: int = 4,
        log_dir: str | None = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.leak_dir = leak_dir
        self.max_workers = max_workers
        self.log_dir = log_dir or str(RUNS_ROOT / "logs")

    def run(
        self,
        target_name: str,
        known_phones: list[str] | None = None,
        known_usernames: list[str] | None = None,
        modules: list[str] | None = None,
    ) -> ReconReport:
        """Run deep recon with priority-based parallel workers."""
        known_phones = known_phones or []
        known_usernames = known_usernames or []

        # Resolve module preset
        if modules and len(modules) == 1 and modules[0] in MODULE_PRESETS:
            modules = MODULE_PRESETS[modules[0]]
        elif not modules:
            modules = list(MODULES.keys())

        # Build task list sorted by priority (P0 first)
        tasks: list[ReconTask] = []
        errors: list[dict] = []
        for mod_name in modules:
            adapter_cls = MODULES.get(mod_name)
            if not adapter_cls:
                errors.append({"module": mod_name, "error": f"Unknown module: {mod_name}"})
                continue
            tasks.append(ReconTask(
                module_name=mod_name,
                priority=MODULE_PRIORITY.get(mod_name, 3),
                adapter_cls=adapter_cls,
                target_name=target_name,
                known_phones=known_phones,
                known_usernames=known_usernames,
                lane=MODULE_LANE.get(mod_name, "fast"),
                proxy=self.proxy,
                timeout=self.timeout,
                worker_timeout=PRIORITY_WORKER_TIMEOUT.get(MODULE_PRIORITY.get(mod_name, 3), WORKER_TIMEOUT),
                leak_dir=self.leak_dir,
            ))
        tasks.sort()  # by priority ascending (P0 first)

        started = datetime.now().isoformat()
        all_hits: list[ReconHit] = []
        modules_run: list[str] = []
        task_results: list[TaskResult] = []

        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

        # ── Execute with worker pool ──
        n_workers = min(self.max_workers, len(tasks))
        if n_workers == 0:
            n_workers = 1

        print(f"  Dispatching {len(tasks)} task(s) across {n_workers} worker(s)  [Fast Lane → Slow Lane | P0→P3]")

        for lane_name in ("fast", "slow"):
            lane_tasks = [task for task in tasks if task.lane == lane_name]
            if not lane_tasks:
                continue

            lane_workers = min(self.max_workers, len(lane_tasks)) or 1
            print(f"\n  {lane_name.upper()} LANE  ·  {len(lane_tasks)} task(s) across {lane_workers} worker(s)")

            pool = ProcessPoolExecutor(max_workers=lane_workers)
            future_map: dict[Future, ReconTask] = {}
            for task in lane_tasks:
                priority_label = f"P{task.priority}"
                print(f"  [{task.module_name}] Queued  ({priority_label}, {task.adapter_cls.region.upper()} segment)")
                fut = pool.submit(
                    _run_adapter_isolated,
                    adapter_cls_name=task.module_name,
                    region=task.adapter_cls.region,
                    proxy=task.proxy,
                    timeout=task.timeout,
                    leak_dir=task.leak_dir,
                    target_name=task.target_name,
                    known_phones=task.known_phones,
                    known_usernames=task.known_usernames,
                    log_dir=self.log_dir,
                )
                future_map[fut] = task

            completed_futures: set[Future] = set()
            submitted_at = {fut: time.monotonic() for fut in future_map}
            pending = set(future_map)
            lane_started = time.monotonic()
            try:
                while pending:
                    done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)

                    for fut in done:
                        completed_futures.add(fut)
                        task = future_map[fut]
                        try:
                            result_dict = fut.result(timeout=10)
                        except Exception as exc:
                            errors.append({"module": task.module_name, "error": f"worker_crash: {exc}"})
                            print(f"  [{task.module_name}] CRASHED: {exc}")
                            continue

                        modules_run.append(result_dict["module"])
                        if result_dict["error"]:
                            errors.append({"module": result_dict["module"], "error": result_dict["error"]})
                            print(f"  [{result_dict['module']}] ERROR: {result_dict['error']}  ({result_dict['elapsed']:.1f}s)")
                        else:
                            hits = [ReconHit.from_dict(h) for h in result_dict["hits"]]
                            all_hits.extend(hits)
                            print(f"  [{result_dict['module']}] → {len(hits)} hit(s)  ({result_dict['elapsed']:.1f}s)")

                        task_results.append(TaskResult(
                            module_name=result_dict["module"],
                            lane=task.lane,
                            hits=[],
                            error=result_dict["error"],
                            elapsed_sec=result_dict["elapsed"],
                            raw_log_path=result_dict["log_path"],
                        ))

                    now = time.monotonic()
                    timed_out: list[Future] = []
                    for fut in pending:
                        task = future_map[fut]
                        if now - submitted_at[fut] >= task.worker_timeout:
                            timed_out.append(fut)

                    for fut in timed_out:
                        pending.remove(fut)
                        task = future_map[fut]
                        fut.cancel()
                        errors.append({"module": task.module_name, "error": f"TIMEOUT ({int(task.worker_timeout)}s)"})
                        print(f"  [{task.module_name}] TIMEOUT after {int(task.worker_timeout)}s — cancelled")
                        task_results.append(TaskResult(
                            module_name=task.module_name,
                            lane=task.lane,
                            hits=[],
                            error=f"TIMEOUT ({int(task.worker_timeout)}s)",
                            elapsed_sec=float(task.worker_timeout),
                            raw_log_path="",
                        ))
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            lane_elapsed = time.monotonic() - lane_started
            lane_hits = sum(1 for item in task_results if item.lane == lane_name and not item.error)
            print(f"  {lane_name.upper()} LANE complete  ·  {lane_hits}/{len(lane_tasks)} task(s) finished cleanly in {lane_elapsed:.1f}s")

        # Deduplicate hits by fingerprint
        seen: dict[str, ReconHit] = {}
        for hit in all_hits:
            fp = hit.fingerprint
            if fp in seen:
                # Merge: keep higher confidence, accumulate cross_refs
                existing = seen[fp]
                if hit.confidence > existing.confidence:
                    existing.confidence = hit.confidence
                    existing.source_detail = hit.source_detail
                existing.cross_refs = list(set(existing.cross_refs + hit.cross_refs))
            else:
                seen[fp] = hit

        deduped = list(seen.values())

        # Identify cross-confirmed hits (found by 2+ modules)
        source_counts: dict[str, set[str]] = {}
        for hit in all_hits:
            source_counts.setdefault(hit.fingerprint, set()).add(hit.source_module)
        cross_confirmed = [
            h for h in deduped
            if len(source_counts.get(h.fingerprint, set())) >= 2
        ]
        for h in cross_confirmed:
            h.confidence = min(1.0, h.confidence + 0.2)  # boost for multi-source

        # Classify new phones/emails
        known_set = set(known_phones)
        new_phones = sorted({h.value for h in deduped if h.observable_type == "phone" and h.value not in known_set and h.confidence > 0})
        new_emails = sorted({h.value for h in deduped if h.observable_type == "email" and h.confidence > 0})

        report = ReconReport(
            target_name=target_name,
            modules_run=modules_run,
            hits=deduped,
            errors=errors,
            started_at=started,
            finished_at=datetime.now().isoformat(),
            new_phones=new_phones,
            new_emails=new_emails,
            cross_confirmed=cross_confirmed,
        )

        return report

    @staticmethod
    def report_summary(report: ReconReport) -> str:
        """Human-readable summary of deep recon results."""
        # Classify hits by type
        infra_hits = [h for h in report.hits if h.observable_type == "infrastructure"]
        url_hits = [h for h in report.hits if h.observable_type == "url"]
        coord_hits = [h for h in report.hits if h.observable_type == "coordinates"]
        loc_hits = [h for h in report.hits if h.observable_type == "location"]

        lines = [
            f"=== Deep Recon Report: {report.target_name} ===",
            f"Modules run: {', '.join(report.modules_run)}",
            f"Time: {report.started_at} → {report.finished_at}",
            f"Total hits: {len(report.hits)}",
            f"New phones: {len(report.new_phones)}",
            f"New emails: {len(report.new_emails)}",
            f"Infrastructure: {len(infra_hits)}",
            f"URLs discovered: {len(url_hits)}",
            f"Coordinates: {len(coord_hits)}",
            f"Locations: {len(loc_hits)}",
            f"Cross-confirmed: {len(report.cross_confirmed)}",
        ]

        if report.new_phones:
            lines.append("\n📱 New Phone Numbers Found:")
            for phone in report.new_phones:
                best = max((h for h in report.hits if h.value == phone), key=lambda h: h.confidence)
                xconf = " ✓✓ CROSS-CONFIRMED" if any(h.fingerprint == best.fingerprint for h in report.cross_confirmed) else ""
                lines.append(f"  {phone}  (conf={best.confidence:.0%}, via {best.source_detail}){xconf}")

        if report.new_emails:
            lines.append("\n📧 New Emails Found:")
            for email in report.new_emails:
                best = max((h for h in report.hits if h.value == email), key=lambda h: h.confidence)
                lines.append(f"  {email}  (conf={best.confidence:.0%}, via {best.source_detail})")

        if infra_hits:
            lines.append("\n🏗️ Infrastructure:")
            for h in sorted(infra_hits, key=lambda x: -x.confidence)[:15]:
                lines.append(f"  {h.value}  (conf={h.confidence:.0%}, via {h.source_detail})")

        if coord_hits:
            lines.append("\n📍 GEOINT Coordinates:")
            for h in coord_hits:
                lines.append(f"  {h.value}  (from {h.source_detail})")

        if loc_hits:
            lines.append("\n🗺️ Locations Resolved:")
            for h in loc_hits:
                lines.append(f"  {h.value[:80]}  (via {h.source_detail})")

        if url_hits:
            lines.append(f"\n🔗 URLs Found: {len(url_hits)} (top 10):")
            for h in sorted(url_hits, key=lambda x: -x.confidence)[:10]:
                lines.append(f"  {h.value}  (conf={h.confidence:.0%}, via {h.source_detail})")

        if report.errors:
            lines.append(f"\n⚠️ Errors: {len(report.errors)}")
            for err in report.errors:
                lines.append(f"  [{err['module']}] {err['error']}")

        return "\n".join(lines)


# ── CLI entry point ──────────────────────────────────────────────

def _cli():
    """
    HANNA Deep Recon — Hybrid CLI

    Usage:
      python3 deep_recon.py --module ashok --target example.com
      python3 deep_recon.py --mode full-spectrum --target "Hanna Dosenko" --phones +380507133698
      python3 deep_recon.py --list-modules
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="deep_recon",
        description="HANNA Deep Recon v2 — UA/RU OSINT multi-adapter runner",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--module", metavar="NAME", help="Run a single adapter (e.g. ashok, ua_leak, ghunt)")
    group.add_argument("--mode", metavar="PRESET", help="Run a preset (e.g. full-spectrum, milint, deep-ua)")
    group.add_argument("--list-modules", action="store_true", help="List available modules and presets")

    parser.add_argument("--target", metavar="NAME", help="Target full name (required for module/mode runs)")
    parser.add_argument("--phones", nargs="*", default=[], metavar="PHONE", help="Known phone numbers (+380...)")
    parser.add_argument("--usernames", nargs="*", default=[], metavar="USER", help="Known usernames / domains")
    parser.add_argument("--proxy", metavar="URL", help="SOCKS5/HTTP proxy (e.g. socks5h://127.0.0.1:9050)")
    parser.add_argument("--leak-dir", metavar="PATH", help="Directory with JSONL leak files")
    parser.add_argument("--timeout", type=float, default=10.0, metavar="SEC", help="Per-request timeout (default: 10)")
    parser.add_argument("--output-dir", metavar="DIR", help="Save JSON report to this directory")

    args = parser.parse_args()

    # ── List modules ──
    if args.list_modules:
        print("Available modules:")
        for name, cls in MODULES.items():
            print(f"  {name:20s}  [{cls.region.upper():6s}]  {cls.__doc__.strip().splitlines()[0] if cls.__doc__ else ''}")
        print("\nPresets:")
        for preset, mods in MODULE_PRESETS.items():
            print(f"  {preset:20s}  → {', '.join(mods)}")
        return

    # ── Validate ──
    if not args.target:
        parser.error("--target is required when running modules (use --list-modules to browse)")

    # ── Resolve module list ──
    if args.module:
        if args.module not in MODULES:
            parser.error(f"Unknown module '{args.module}'. Use --list-modules to see available.")
        modules = [args.module]
    elif args.mode:
        if args.mode in MODULE_PRESETS:
            modules = MODULE_PRESETS[args.mode]
        elif args.mode in MODULES:
            modules = [args.mode]
        else:
            parser.error(f"Unknown preset/module '{args.mode}'. Use --list-modules to see available.")
    else:
        modules = MODULE_PRESETS["full-spectrum"]

    # ── Run ──
    runner = DeepReconRunner(
        proxy=args.proxy,
        timeout=args.timeout,
        leak_dir=args.leak_dir,
    )

    print(f"\n{'='*60}")
    print(f"  HANNA Deep Recon — {args.target}")
    print(f"  Modules: {', '.join(modules)}")
    if args.phones:
        print(f"  Known phones: {', '.join(args.phones)}")
    if args.usernames:
        print(f"  Known usernames: {', '.join(args.usernames)}")
    print(f"{'='*60}\n")

    report = runner.run(
        target_name=args.target,
        known_phones=args.phones,
        known_usernames=args.usernames,
        modules=modules,
    )

    # ── Output ──
    summary = DeepReconRunner.report_summary(report)
    print(f"\n{summary}")

    # ── Save JSON report ──
    out_dir = Path(args.output_dir) if args.output_dir else RUNS_ROOT
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"deep_recon_{ts}.json"
    report_data = {
        "target": report.target_name,
        "modules": report.modules_run,
        "started": report.started_at,
        "finished": report.finished_at,
        "total_hits": len(report.hits),
        "new_phones": report.new_phones,
        "new_emails": report.new_emails,
        "cross_confirmed": len(report.cross_confirmed),
        "hits": [
            {
                "type": h.observable_type,
                "value": h.value,
                "source": h.source_module,
                "detail": h.source_detail,
                "confidence": h.confidence,
                "cross_refs": h.cross_refs,
            }
            for h in report.hits
        ],
        "errors": report.errors,
    }
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 Report saved: {report_path}")


if __name__ == "__main__":
    _cli()
