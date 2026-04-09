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
from functools import lru_cache
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


class UnsupportedProxyError(AdapterExecutionError):
    """Raised when an adapter cannot safely honor proxy/Tor routing."""

    error_kind = "unsupported_proxy"

    def __init__(self, detail: str):
        super().__init__(detail)


def derive_runtime_issue(adapter: "ReconAdapter", hits: list["ReconHit"]) -> dict[str, str] | None:
    """Promote hidden adapter degradation into explicit runtime errors."""
    if hits:
        return None

    diagnostics = adapter.runtime_diagnostics()
    if not diagnostics.get("healthy", True):
        failures = int(diagnostics.get("consecutive_failures", 0))
        return {
            "error": f"auto-disabled after {failures} consecutive failures",
            "error_kind": "auto_disabled",
        }

    noop_reason_raw = diagnostics.get("noop_reason")
    noop_reason = noop_reason_raw.strip() if isinstance(noop_reason_raw, str) else ""
    if noop_reason:
        return {
            "error": f"silent no-op: {noop_reason}",
            "error_kind": "silent_noop",
        }

    return None


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
class ReconModuleOutcome:
    """Per-module execution outcome for deep recon sessions."""
    module_name: str
    lane: str
    hits: list[ReconHit] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    elapsed_sec: float = 0.0
    log_path: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "lane": self.lane,
            "hits": [hit.to_dict() for hit in self.hits],
            "error": self.error,
            "error_kind": self.error_kind,
            "elapsed_sec": self.elapsed_sec,
            "log_path": self.log_path,
        }

    def to_error_dict(self) -> dict[str, Any] | None:
        if not self.error:
            return None
        payload: dict[str, Any] = {
            "module": self.module_name,
            "error": self.error,
        }
        if self.error_kind:
            payload["error_kind"] = self.error_kind
        return payload


@dataclass
class ReconReport:
    """Aggregated result of a deep recon session."""
    target_name: str
    modules_run: list[str]
    hits: list[ReconHit]
    started_at: str
    finished_at: str = ""
    new_phones: list[str] = field(default_factory=list)
    new_emails: list[str] = field(default_factory=list)
    cross_confirmed: list[ReconHit] = field(default_factory=list)  # found in 2+ sources
    outcomes: list[ReconModuleOutcome] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        standalone_errors: list[dict[str, Any]] = []
        for raw_error in self.errors:
            normalized = self._normalize_error_entry(raw_error)
            if not normalized:
                continue

            module_name = str(normalized.get("module", "")).strip()
            message = str(normalized.get("error", "")).strip()
            error_kind = str(normalized.get("error_kind", "")).strip() or None
            if module_name:
                outcome = next((item for item in self.outcomes if item.module_name == module_name), None)
                if outcome is None:
                    self.outcomes.append(ReconModuleOutcome(
                        module_name=module_name,
                        lane="unknown",
                        error=message,
                        error_kind=error_kind,
                    ))
                    continue
                if not outcome.error:
                    outcome.error = message
                    outcome.error_kind = error_kind
                    continue
                if outcome.error == message and outcome.error_kind == error_kind:
                    continue

            standalone_errors.append(normalized)

        self.errors = self._collect_error_entries(standalone_errors)

    @staticmethod
    def _normalize_error_entry(raw_error: Any) -> dict[str, Any] | None:
        if isinstance(raw_error, dict):
            message = str(raw_error.get("error", "")).strip()
            if not message:
                return None
            payload: dict[str, Any] = {"error": message}
            module_name = str(raw_error.get("module", "")).strip()
            if module_name:
                payload["module"] = module_name
            error_kind = str(raw_error.get("error_kind", "")).strip()
            if error_kind:
                payload["error_kind"] = error_kind
            return payload
        if isinstance(raw_error, str) and raw_error.strip():
            return {"error": raw_error.strip()}
        return None

    def _collect_error_entries(self, standalone_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str | None]] = set()

        def _append(entry: dict[str, Any]) -> None:
            module_name = str(entry.get("module", "")).strip()
            message = str(entry.get("error", "")).strip()
            error_kind_raw = entry.get("error_kind")
            error_kind = str(error_kind_raw).strip() if error_kind_raw else None
            key = (module_name, message, error_kind)
            if not message or key in seen:
                return
            seen.add(key)
            payload: dict[str, Any] = {"error": message}
            if module_name:
                payload["module"] = module_name
            if error_kind:
                payload["error_kind"] = error_kind
            entries.append(payload)

        for outcome in self.outcomes:
            entry = outcome.to_error_dict()
            if entry:
                _append(entry)
        for entry in standalone_errors:
            _append(entry)
        return entries


# ── Phone normalization ──────────────────────────────────────────

_UA_PHONE_RE = re.compile(r"(?:\+?380|0)\d{9}")
_RU_PHONE_RE = re.compile(r"(?:\+?7|8)\d{10}")
_GENERIC_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{7,15}\d")


@lru_cache(maxsize=4096)
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
        self._fetch_attempts = 0
        self._post_attempts = 0
        self._noop_reason: str | None = None
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy,
                "https": proxy,
            })
            self._opener = urllib.request.build_opener(proxy_handler)

    def _record_noop(self, reason: str) -> None:
        """Store a human-readable reason when the adapter legitimately did no work."""
        if reason and not self._noop_reason:
            self._noop_reason = reason

    def runtime_diagnostics(self) -> dict[str, Any]:
        """Expose post-run adapter health for runner-level accounting."""
        return {
            "healthy": self._is_healthy,
            "consecutive_failures": self._consecutive_failures,
            "fetch_attempts": self._fetch_attempts,
            "post_attempts": self._post_attempts,
            "noop_reason": self._noop_reason,
        }

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
        self._fetch_attempts += 1
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
        self._post_attempts += 1
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
