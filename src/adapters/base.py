"""
adapters.base — ReconAdapter ABC, data structures, and phone utilities.
"""
from __future__ import annotations

import json
import logging
import random
import re
import socket
import time
import urllib.request
import urllib.error
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import (
    ADAPTER_FAILURE_THRESHOLD,
    REQUIRE_PROXY,
    RETRY_BASE_DELAY,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
)

log = logging.getLogger("hanna.recon")


class AdapterExecutionError(RuntimeError):
    """Base exception for structured adapter execution failures."""

    error_kind = "adapter_error"


class MissingCredentialsError(AdapterExecutionError):
    """Raised when an adapter cannot run because required credentials are absent."""

    error_kind = "missing_credentials"

    def __init__(self, *credential_names: str):
        self.credential_names = [name for name in credential_names if name]
        detail = ", ".join(self.credential_names) if self.credential_names else "credentials"
        super().__init__(f"missing credentials: {detail}")


class MissingBinaryError(AdapterExecutionError):
    """Raised when a required CLI binary cannot be found."""

    error_kind = "missing_binary"

    def __init__(self, binary_name: str):
        self.binary_name = binary_name
        super().__init__(f"missing binary: {binary_name}")


class DependencyUnavailableError(AdapterExecutionError):
    """Raised when an external dependency exists but cannot be executed."""

    error_kind = "dependency_unavailable"

    def __init__(self, detail: str):
        super().__init__(f"dependency unavailable: {detail}")


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
