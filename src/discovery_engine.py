"""
discovery_engine.py — Recursive Discovery Orchestrator
=====================================================

Middleware between raw OSINT tool outputs and the claim/entity pipeline.
Implements:
  1. Input Validation Layer   — rejects garbage targets, artifact hashes, profile→target mismatches
  2. Observable Extractor     — regex-extracts phones, emails, usernames, domains, URLs from tool logs
  3. Entity Resolution        — multi-source corroboration + session-level linking (NOT day-level)
  4. Discovery Queue (SQLite) — tracks discovered observables and auto-pivot tasks
  5. Verification Layer       — HTTP HEAD check for profile URLs, tiered confidence

v2.0 — Verification-First Architecture
  - NO day-level co-occurrence (was linking unrelated targets from same calendar day)
  - NO default-to-username for unknown strings (was treating SHA hashes as usernames)
  - NO 100% confidence from quantity (was rewarding garbage volume)
  - Multi-source corroboration required for Confirmed tier
  - Profile URL verification via HTTP HEAD (opt-in)
  - Tiered display: Confirmed / Probable / Unverified

Usage:
    engine = DiscoveryEngine(db_path="discovery.db")
    # Ingest all legacy metadata exports
    for meta_path in metadata_json_paths:
        engine.ingest_metadata(meta_path)
    # Resolve entities into identity clusters
    engine.resolve_entities()
    engine.verify_profiles()  # optional, hits network
    html = engine.render_graph_report()
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import math
import os
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from config import (
    DEFAULT_DB_PATH,
    MAX_BODY_BYTES,
    MAX_DISCOVERY_DEPTH,
    MAX_PROFILE_URLS,
    RUNS_ROOT,
    SCHEMA_VERSION,
    VERIFY_WORKERS,
)
from net import proxy_aware_request
from observable_extractor import ObservableExtractor
from profile_verifier import ProfileVerifier
from report_renderer import ReportRenderer

log = logging.getLogger("hanna.discovery")

# ── Constants ──────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{7,15}\d")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
_DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+"
    r"(?:com|net|org|io|info|ua|de|ru|uk|co|me|tv|xyz|pro|biz|int)\b"
)
_USERNAME_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:facebook|instagram|twitter|x|linkedin|github|tiktok|vk|telegram"
    r"|pinterest|reddit|youtube|twitch|snapchat|medium|behance"
    r"|dribbble|flickr|tumblr|soundcloud|spotify|patreon"
    r"|duolingo|kaggle|roblox|opensea)"
    r"\.(?:com|io|tv|gg|me)/(?:@)?([a-zA-Z0-9_.]{2,40})"
)
_SHERLOCK_HIT_RE = re.compile(r"^\[\+\]\s+\S+:\s+(https?://\S+)", re.MULTILINE)
_MAIGRET_HIT_RE = re.compile(r"^\[\+\]\s+\S+.*?:\s+(https?://\S+)", re.MULTILINE)

# Garbage filters — targets matching these are rejected
_GARBAGE_PATTERNS = [
    re.compile(r"Ignored\s+invalid", re.IGNORECASE),
    re.compile(r"^\[FTL\]"),
    re.compile(r"^ERROR\s"),
    re.compile(r"missing.*flag\s+required", re.IGNORECASE),
    re.compile(r"^Unable\s+to\s+parse"),
    re.compile(r"^\s*$"),  # blank
]

MAX_DISCOVERY_DEPTH = MAX_DISCOVERY_DEPTH  # re-exported from config

# ── Phase 1 Constants: Anti-false-positive filters ──────────────

# Placeholder/noise domains — never register as observables
_PLACEHOLDER_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "test.com",
    "localhost", "invalid", "local",
})

# Username: alphanumeric + limited special chars, 2-40 chars
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@\- ]{2,40}$")

# Hex-only strings ≥16 chars — SHA/MD5 hashes, NOT usernames
_HEX_ONLY_RE = re.compile(r"^[a-fA-F0-9]{16,}$")

# Entropy threshold: SHA256 ~ 4.0 bits/char; real usernames < 3.5
_ENTROPY_THRESHOLD = 3.8

# ucoz-family domains for platform deduplication
_UCOZ_DOMAINS = frozenset({
    "ucoz.ru", "ucoz.ua", "ucoz.com", "ucoz.net", "ucoz.org",
    "at.ua", "my1.ru", "3dn.ru", "clan.su", "do.am",
    "org.ua", "pp.ua", "net.ua",
})

# Platforms that return HTTP 200 for ANY username — false-positive factories
_FALSE_POSITIVE_PLATFORMS = frozenset({
    "3ddd", "cs-strikez", "duolingo", "kaskus", "listography",
    "livemaster", "mercadolivre", "ucoz", "wordnik",
    "1001mem", "memrise", "colourlovers", "reverbnation",
    "reddit",
})

_REDACTION_MODES = frozenset({"internal", "shareable", "strict"})

# Verification tier constants
TIER_CONFIRMED = "confirmed"     # Multi-source corroboration OR original target
TIER_PROBABLE = "probable"       # Single source, plausible context
TIER_UNVERIFIED = "unverified"   # Single source, no corroboration


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy in bits per character."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s.lower():
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"[\s\-\(\)]", "", raw)
    if not re.fullmatch(r"\+?\d{7,15}", digits):
        return None
    if not digits.startswith("+") and len(digits) >= 10:
        digits = "+" + digits
    return digits


def _normalize_domain(raw: str) -> str | None:
    d = raw.lower().strip().rstrip(".")
    if len(d) < 4 or "." not in d:
        return None
    # reject IPs
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", d):
        return None
    return d


def _is_garbage_target(value: str) -> bool:
    cleaned = strip_ansi(value).strip()
    if not cleaned or len(cleaned) < 2:
        return True
    for pat in _GARBAGE_PATTERNS:
        if pat.search(cleaned):
            return True
    return False


# ── Data classes ───────────────────────────────────────────────────

@dataclass
class Observable:
    """A single discovered observable."""
    obs_type: str          # phone, email, username, domain, url
    value: str             # normalized value
    source_tool: str       # which tool found it
    source_target: str     # original target that was queried
    source_file: str       # metadata JSON path
    depth: int = 0         # discovery depth (0 = seed, 1 = first pivot, …)
    raw: str = ""          # original raw text
    urls: list[str] = field(default_factory=list)
    is_original_target: bool = False        # was this the investigation input?
    source_tools: set[str] = field(default_factory=set)  # all tools that found this
    tier: str = TIER_UNVERIFIED             # confirmed / probable / unverified

    @property
    def fingerprint(self) -> str:
        return f"{self.obs_type}:{self.value}"


@dataclass
class IdentityCluster:
    """A resolved identity — one real-world entity."""
    person_id: str
    label: str                                # display name
    observables: list[Observable] = field(default_factory=list)
    profile_urls: list[str] = field(default_factory=list)
    confidence: float = 0.0
    sources: set[str] = field(default_factory=set)


# ── Discovery Engine ──────────────────────────────────────────────

class DiscoveryEngine:
    """
    Recursive discovery orchestrator.

    Workflow:
      1. ingest_metadata()  — load legacy JSON exports, validate, extract observables
      2. resolve_entities() — cluster observables into identity anchors
      3. get_pivot_queue()  — return observables discovered but not yet pivoted
      4. render_graph_report() — generate person-centric HTML dossier
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self._init_schema()
        self.clusters: list[IdentityCluster] = []
        self._all_observables: list[Observable] = []
        self._obs_by_value: dict[str, Observable] = {}  # fingerprint -> Observable (dedup + corroboration)
        self._obs_lookup: dict[str, Observable] = {}
        self._metas: list[dict[str, Any]] = []
        self._tool_stats: dict[str, dict[str, int]] = {}  # tool -> {success, failed, observables}
        self._confirmed_imports: list[dict[str, Any]] = []
        self.extractor = ObservableExtractor({
            "extract_observables": self._extract_observables,
            "classify_and_register": self._classify_and_register,
            "infer_type": self._infer_type,
            "normalize": self._normalize,
            "extract_from_phone_log": self._extract_from_phone_log,
            "extract_from_username_log": self._extract_from_username_log,
            "extract_from_domain_log": self._extract_from_domain_log,
            "extract_generic": self._extract_generic,
            "platform_from_url": self._platform_from_url,
        })
        self.verifier = ProfileVerifier(self, false_positive_platforms=_FALSE_POSITIVE_PLATFORMS)
        self.renderer = ReportRenderer(
            self,
            placeholder_domains=_PLACEHOLDER_DOMAINS,
            redaction_modes=_REDACTION_MODES,
            strip_ansi=strip_ansi,
        )

    def _init_schema(self):
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observables (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                obs_type    TEXT NOT NULL,
                value       TEXT NOT NULL,
                raw         TEXT,
                source_tool TEXT,
                source_target TEXT,
                source_file TEXT,
                depth       INTEGER DEFAULT 0,
                is_original_target INTEGER DEFAULT 0,
                corroboration_count INTEGER DEFAULT 1,
                tier        TEXT DEFAULT 'unverified',
                discovered_at TEXT DEFAULT (datetime('now')),
                raw_log_ref TEXT,
                UNIQUE(obs_type, value)
            );
            CREATE TABLE IF NOT EXISTS discovery_queue (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                obs_type    TEXT NOT NULL,
                value       TEXT NOT NULL,
                suggested_tools TEXT,  -- JSON array
                reason      TEXT,
                priority    INTEGER DEFAULT 0,
                state       TEXT DEFAULT 'pending',  -- pending | running | done | skipped
                depth       INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now')),
                started_at  TEXT,
                finished_at TEXT,
                UNIQUE(obs_type, value)
            );
            CREATE TABLE IF NOT EXISTS entity_links (
                obs_a_type  TEXT NOT NULL,
                obs_a_value TEXT NOT NULL,
                obs_b_type  TEXT NOT NULL,
                obs_b_value TEXT NOT NULL,
                link_reason TEXT,
                confidence  REAL DEFAULT 0.5,
                PRIMARY KEY (obs_a_type, obs_a_value, obs_b_type, obs_b_value)
            );
            CREATE TABLE IF NOT EXISTS profile_urls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                platform    TEXT,
                url         TEXT NOT NULL,
                source_tool TEXT,
                status      TEXT DEFAULT 'unchecked',
                content_match INTEGER DEFAULT 0,
                checked_at  TEXT,
                valid_until TEXT,
                last_checked_at TEXT,
                raw_log_ref TEXT,
                UNIQUE(url)
            );
            CREATE TABLE IF NOT EXISTS rejected_targets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT,
                raw_target  TEXT,
                reason      TEXT,
                rejected_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self.db.commit()
        self._migrate_schema()
        self._check_schema_version()

    def _check_schema_version(self):
        """Enforce schema versioning via PRAGMA user_version."""
        current = self.db.execute("PRAGMA user_version").fetchone()[0]
        if current == 0:
            # Fresh DB or pre-versioning DB — stamp current version
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.db.commit()
        elif current < SCHEMA_VERSION:
            # Future migrations go here based on current version
            log.info("Schema upgrade: %d → %d", current, SCHEMA_VERSION)
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.db.commit()
        elif current > SCHEMA_VERSION:
            log.warning("DB schema version %d is newer than engine version %d", current, SCHEMA_VERSION)

    def _migrate_schema(self):
        """Safe ALTER TABLE migrations for existing databases."""
        migrations = [
            ("observables", "raw_log_ref", "TEXT"),
            ("profile_urls", "valid_until", "TEXT"),
            ("profile_urls", "last_checked_at", "TEXT"),
            ("profile_urls", "raw_log_ref", "TEXT"),
        ]
        for table, column, col_type in migrations:
            try:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # Keep rejected-target metrics stable across repeated runs of the same artifacts.
        self.db.execute(
            "DELETE FROM rejected_targets "
            "WHERE id NOT IN ("
            "  SELECT MIN(id) FROM rejected_targets GROUP BY source_file, raw_target, reason"
            ")"
        )
        self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_rejected_targets_unique "
            "ON rejected_targets(source_file, raw_target, reason)"
        )
        self.db.commit()

    def _record_rejected_target(self, source_file: str, raw_target: str, reason: str, *, commit: bool = True) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO rejected_targets (source_file, raw_target, reason) VALUES (?, ?, ?)",
            (source_file, raw_target, reason),
        )
        if commit:
            self.db.commit()

    # ── 1.  Input Validation + Ingestion ──────────────────────────

    def ingest_metadata(self, meta_path: str | Path) -> dict[str, Any]:
        """Load a single legacy metadata JSON, validate, extract observables."""
        meta_path = Path(meta_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw_target = strip_ansi(str(meta.get("target") or ""))
        profile = str(meta.get("profile") or "unknown")
        status = str(meta.get("status") or "unknown")
        log_file = meta.get("log_file", "")
        file_sha256 = meta.get("sha256", "")

        # Update tool stats
        stats = self._tool_stats.setdefault(profile, {"success": 0, "failed": 0, "observables": 0})
        if status == "success":
            stats["success"] += 1
        else:
            stats["failed"] += 1

        # ── Phase 1: Defense in Depth — Input Validation ────────────

        # 1a. Reject garbage targets (ANSI artifacts, errors, blanks)
        if _is_garbage_target(raw_target):
            self._record_rejected_target(str(meta_path), raw_target, "garbage_target_filter")
            return {"status": "rejected", "reason": "garbage_target", "raw": raw_target}

        # 1b. Reject when target IS the file's SHA256 hash (artifact, not a human identifier)
        if file_sha256 and raw_target == file_sha256:
            self._record_rejected_target(str(meta_path), raw_target, "target_is_file_hash")
            return {"status": "rejected", "reason": "target_is_file_hash", "raw": raw_target}

        # 1c. Reject hex-only targets (SHA hashes used as phoneinfoga / maigret input)
        if _HEX_ONLY_RE.fullmatch(raw_target):
            self._record_rejected_target(str(meta_path), raw_target, "hex_hash_target")
            return {"status": "rejected", "reason": "hex_hash_target", "raw": raw_target}

        # 1d. Entropy check — high-entropy strings are hashes/tokens, not human identifiers
        if len(raw_target) >= 16 and _shannon_entropy(raw_target) > _ENTROPY_THRESHOLD:
            self._record_rejected_target(str(meta_path), raw_target, "high_entropy_target")
            return {"status": "rejected", "reason": "high_entropy_target", "raw": raw_target}

        # 1e. Profile → target type validation
        if profile == "phone" and not _normalize_phone(raw_target):
            self._record_rejected_target(str(meta_path), raw_target, "phone_profile_invalid_target")
            return {"status": "rejected", "reason": "phone_profile_invalid_target", "raw": raw_target}

        if profile == "domain" and raw_target.lower().strip().rstrip(".") in _PLACEHOLDER_DOMAINS:
            self._record_rejected_target(str(meta_path), raw_target, "placeholder_domain")
            return {"status": "rejected", "reason": "placeholder_domain", "raw": raw_target}

        if profile == "health":
            return {"status": "skipped", "reason": "health_check"}

        # Read log file
        if not log_file or not Path(log_file).exists():
            return {"status": "skipped", "reason": "no_log_file"}
        log_text = Path(log_file).read_text(encoding="utf-8", errors="replace")
        log_text = strip_ansi(log_text)

        # Store valid meta
        meta["target"] = raw_target
        meta["_log_text"] = log_text
        meta["_source_file"] = str(meta_path)
        meta["_label"] = meta.get("label", "")
        self._metas.append(meta)

        # Extract observables from the log
        extracted = self._extract_observables(log_text, profile, raw_target, str(meta_path))
        stats["observables"] += len(extracted)

        return {"status": "ingested", "profile": profile, "target": raw_target, "observables": len(extracted)}

    def ingest_confirmed_evidence(self, evidence_path: str | Path) -> dict[str, Any]:
        """Ingest analyst-confirmed evidence from a JSON manifest."""
        evidence_path = Path(evidence_path)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))

        if isinstance(payload, dict):
            entries = payload.get("entries", [])
            default_target = str(payload.get("target") or "")
            default_source = str(payload.get("source_tool") or "confirmed_import")
            batch_label = str(payload.get("label") or evidence_path.stem)
        elif isinstance(payload, list):
            entries = payload
            default_target = ""
            default_source = "confirmed_import"
            batch_label = evidence_path.stem
        else:
            raise ValueError("Confirmed evidence manifest must be a JSON object or list")

        imported = 0
        duplicates = 0
        target_anchor: Observable | None = None
        if default_target:
            seed_obs = self._classify_and_register(
                value=default_target,
                source_tool=default_source,
                source_target=default_target,
                source_file=str(evidence_path),
                depth=0,
                is_original_target=True,
                commit=False,
            )
            if seed_obs:
                seed_obs.tier = TIER_CONFIRMED
                target_anchor = seed_obs
                self.db.execute(
                    "UPDATE observables SET tier = ? WHERE obs_type = ? AND value = ?",
                    (TIER_CONFIRMED, seed_obs.obs_type, seed_obs.value),
                )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            obs_type = str(entry.get("type") or entry.get("obs_type") or "").strip()
            value = str(entry.get("value") or "").strip()
            if not obs_type or not value:
                continue

            source_tool = str(entry.get("source_tool") or default_source or "confirmed_import")
            source_target = str(entry.get("source_target") or default_target or value)
            source_file = str(evidence_path)
            normalized = self._normalize(obs_type, value) if obs_type in {"phone", "domain", "email", "username", "url"} else value.strip()
            if not normalized:
                continue

            fp = f"{obs_type}:{normalized}"
            existing = self._obs_by_value.get(fp)
            if existing:
                existing.source_tools.add(source_tool)
                existing.tier = TIER_CONFIRMED
                self.db.execute(
                    "UPDATE observables SET tier = ?, corroboration_count = corroboration_count + 1 WHERE obs_type = ? AND value = ?",
                    (TIER_CONFIRMED, obs_type, normalized),
                )
                duplicates += 1
                continue

            obs = Observable(
                obs_type=obs_type,
                value=normalized,
                source_tool=source_tool,
                source_target=source_target,
                source_file=source_file,
                depth=int(entry.get("depth", 1)),
                raw=value,
                is_original_target=bool(entry.get("is_original_target", False)),
                source_tools={source_tool},
                tier=TIER_CONFIRMED,
            )
            self.db.execute(
                "INSERT OR IGNORE INTO observables (obs_type, value, raw, source_tool, source_target, source_file, depth, is_original_target, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (obs.obs_type, obs.value, obs.raw, obs.source_tool, obs.source_target, obs.source_file, obs.depth, 1 if obs.is_original_target else 0, obs.tier),
            )
            self._cache_observable(obs)
            if target_anchor and target_anchor.fingerprint != obs.fingerprint:
                self._link_observables(target_anchor, obs, "confirmed_manifest", 0.95)
            imported += 1

        tool_stats = self._tool_stats.setdefault(default_source, {"success": 0, "failed": 0, "observables": 0})
        tool_stats["success"] += 1
        tool_stats["observables"] += imported
        self._confirmed_imports.append({
            "path": str(evidence_path),
            "label": batch_label,
            "imported": imported,
            "duplicates": duplicates,
        })
        self.db.commit()
        return {
            "status": "ingested",
            "label": batch_label,
            "imported": imported,
            "duplicates": duplicates,
        }

    def _extract_observables(self, log_text: str, profile: str, target: str, source_file: str) -> list[Observable]:
        """Extract all observable types from a tool's log output."""
        found: list[Observable] = []

        # Always register the target itself as an observable (original investigation input)
        seed_obs = self._classify_and_register(target, profile, target, source_file, depth=0, is_original_target=True, commit=False)
        if seed_obs:
            found.append(seed_obs)

        if profile == "phone":
            found.extend(self._extract_from_phone_log(log_text, target, source_file, commit=False))
        elif profile in ("username",):
            found.extend(self._extract_from_username_log(log_text, profile, target, source_file, commit=False))
        elif profile in ("domain", "dnsenum", "whatweb"):
            found.extend(self._extract_from_domain_log(log_text, profile, target, source_file, commit=False))

        # Generic: extract all emails, phones, domains from any log
        found.extend(self._extract_generic(log_text, profile, target, source_file, commit=False))

        self.db.commit()

        return found

    def _classify_and_register(self, value: str, source_tool: str, source_target: str, source_file: str, depth: int = 0, is_original_target: bool = False, *, commit: bool = True) -> Observable | None:
        """Classify a value, normalize it, and register in DB. Returns None for unrecognizable types."""
        value = value.strip()
        if not value or _is_garbage_target(value):
            return None

        obs_type = self._infer_type(value)
        if obs_type is None:
            return None  # Unknown type — refuse to guess (was defaulting to "username")

        # Block placeholder domains at registration level
        if obs_type == "domain" and value.lower().strip().rstrip(".") in _PLACEHOLDER_DOMAINS:
            return None

        normalized = self._normalize(obs_type, value)
        if not normalized:
            return None

        # Corroboration tracking: if already registered, update source_tools count
        fp = f"{obs_type}:{normalized}"
        existing = self._obs_by_value.get(fp)
        if existing:
            existing.source_tools.add(source_tool)
            self.db.execute(
                "UPDATE observables SET corroboration_count = corroboration_count + 1, "
                "tier = CASE WHEN corroboration_count >= 2 THEN 'probable' ELSE tier END "
                "WHERE obs_type = ? AND value = ? AND source_tool != ?",
                (obs_type, normalized, source_tool),
            )
            if commit:
                self.db.commit()
            return existing

        obs = Observable(
            obs_type=obs_type, value=normalized, source_tool=source_tool,
            source_target=source_target, source_file=source_file, depth=depth, raw=value,
            is_original_target=is_original_target, source_tools={source_tool},
        )

        self.db.execute(
            "INSERT INTO observables (obs_type, value, raw, source_tool, source_target, source_file, depth, is_original_target) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(obs_type, value) DO UPDATE SET "
            "corroboration_count = corroboration_count + 1, "
            "tier = CASE WHEN excluded.is_original_target = 1 THEN 'confirmed' "
            "WHEN corroboration_count >= 2 THEN 'probable' ELSE tier END",
            (obs.obs_type, obs.value, obs.raw, obs.source_tool, obs.source_target, obs.source_file, obs.depth, 1 if is_original_target else 0),
        )
        if commit:
            self.db.commit()
        self._cache_observable(obs)
        return obs

    def _cache_observable(self, obs: Observable) -> None:
        self._all_observables.append(obs)
        self._obs_by_value[obs.fingerprint] = obs
        if obs.value:
            self._obs_lookup.setdefault(obs.value, obs)
        if obs.raw:
            self._obs_lookup.setdefault(obs.raw, obs)

    def _infer_type(self, value: str) -> str | None:
        """Classify a string. Returns None if unrecognizable (NO catch-all default)."""
        if _EMAIL_RE.fullmatch(value):
            return "email"
        if _PHONE_RE.fullmatch(re.sub(r"[\s\-\(\)]", "", value)):
            return "phone"
        if re.fullmatch(r"https?://.+", value):
            return "url"
        if "." in value and _DOMAIN_RE.fullmatch(value.lower()):
            return "domain"
        # Explicit username validation — NO catch-all default
        if _HEX_ONLY_RE.fullmatch(value):
            return None  # SHA/MD5 hash, not a username
        if len(value) >= 16 and _shannon_entropy(value) > _ENTROPY_THRESHOLD:
            return None  # High entropy → token/hash, not a human identifier
        if _USERNAME_RE.fullmatch(value) and 2 <= len(value) <= 40:
            return "username"
        return None  # Unknown type — refuse to guess

    def _normalize(self, obs_type: str, value: str) -> str | None:
        if obs_type == "phone":
            return _normalize_phone(value)
        if obs_type == "domain":
            return _normalize_domain(value)
        if obs_type == "email":
            return value.lower().strip()
        if obs_type == "username":
            return value.strip()
        if obs_type == "url":
            return value.strip()
        return value.strip() or None

    def _extract_from_phone_log(self, log_text: str, target: str, source_file: str, *, commit: bool = True) -> list[Observable]:
        found: list[Observable] = []
        # Extract E164, local, international from phoneinfoga output
        for label, pattern in [
            ("phone", r"E164:\s*(\+?\d[\d\s\-]{7,15}\d)"),
            ("phone", r"International:\s*(\d{10,15})"),
        ]:
            m = re.search(pattern, log_text)
            if m:
                obs = self._classify_and_register(m.group(1), "phoneinfoga", target, source_file, commit=commit)
                if obs:
                    found.append(obs)
        # Note: Country code (e.g. "UA") is metadata, NOT an observable — don't register it
        return found

    def _extract_from_username_log(self, log_text: str, tool: str, target: str, source_file: str, *, commit: bool = True) -> list[Observable]:
        found: list[Observable] = []
        # Extract profile URLs from sherlock/maigret [+] lines
        for m in _SHERLOCK_HIT_RE.finditer(log_text):
            url = m.group(1).rstrip(")")
            self.db.execute(
                "INSERT OR IGNORE INTO profile_urls (username, platform, url, source_tool) VALUES (?, ?, ?, ?)",
                (target, self._platform_from_url(url), url, tool),
            )
            # Don't extract usernames from URLs — they're mostly the same target or URL path noise
            # The profile URLs table already links username → platform
            # Try to extract domain
            parsed = urlparse(url)
            if parsed.hostname:
                dom = _normalize_domain(parsed.hostname)
                if dom and dom not in ("facebook.com", "instagram.com", "twitter.com", "x.com",
                                       "linkedin.com", "github.com", "google.com", "youtube.com",
                                       "reddit.com", "pinterest.com", "vk.com", "tiktok.com"):
                    # Non-social-media domain might be interesting
                    pass  # don't auto-pivot on every social media domain
        if commit:
            self.db.commit()
        return found

    def _extract_from_domain_log(self, log_text: str, tool: str, target: str, source_file: str, *, commit: bool = True) -> list[Observable]:
        found: list[Observable] = []
        # Skip placeholder domains
        if target.lower().strip().rstrip(".") in _PLACEHOLDER_DOMAINS:
            return found
        # Extract emails from theHarvester (but not tool-internal emails)
        if "@" in log_text:
            for email in set(_EMAIL_RE.findall(log_text)):
                # skip tool author emails and noise
                if any(skip in email for skip in ("edge-security", "example.com", "noreply", "localhost")):
                    continue
                obs = self._classify_and_register(email, tool, target, source_file, depth=1, commit=commit)
                if obs:
                    found.append(obs)
        # Extract subdomains (cap at 20 to avoid noise)
        subdomain_count = 0
        for line in log_text.splitlines():
            line = line.strip()
            if _DOMAIN_RE.fullmatch(line) and line != target:
                obs = self._classify_and_register(line, tool, target, source_file, depth=1, commit=commit)
                if obs:
                    found.append(obs)
                subdomain_count += 1
                if subdomain_count >= 20:
                    break
        return found

    def _extract_generic(self, log_text: str, tool: str, target: str, source_file: str, *, commit: bool = True) -> list[Observable]:
        """Fallback: extract emails, phones from any log text. Only for phone/username tools — domain tools have their own extractor."""
        found: list[Observable] = []
        # Only run generic extraction on phone and username tools (domain tools are too noisy)
        if tool not in ("phone", "phoneinfoga", "username", "sherlock", "maigret"):
            return found
        # Skip very large logs
        if len(log_text) > 200_000:
            return found
        if "@" not in log_text:
            return found
        # Emails (skip tool-internal ones)
        for email in set(_EMAIL_RE.findall(log_text)):
            if any(skip in email for skip in ("edge-security", "example.com", "noreply", "localhost")):
                continue
            obs = self._classify_and_register(email, tool, target, source_file, depth=1, commit=commit)
            if obs and obs not in found:
                found.append(obs)
        return found

    @staticmethod
    def _platform_from_url(url: str) -> str:
        try:
            host = urlparse(url).hostname or ""
            host_clean = host.replace("www.", "")
            # ucoz-family dedup: all ucoz-hosted sites → single "ucoz" platform
            for ucoz_tld in _UCOZ_DOMAINS:
                if host_clean.endswith("." + ucoz_tld) or host_clean == ucoz_tld:
                    return "ucoz"
            parts = host_clean.split(".")
            return parts[0] if parts else "unknown"
        except Exception:
            return "unknown"

    # ── 2.  Entity Resolution ─────────────────────────────────────

    def resolve_entities(self) -> list[IdentityCluster]:
        """
        Cluster all observables into identity anchors.

        v2 Strategy:
         - Step 1: File-level co-occurrence (SAME log file = same tool session)
         - Step 2: Pipeline-label co-occurrence (same minute, NOT same calendar day)
         - Step 3: Name-matching heuristic (username 'hannadosenko' ~ 'Hanna Dosenko')
         - Step 4: Assign verification tiers based on corroboration
         - Step 5: Transitive closure → clusters

        REMOVED: Day-level [:8] grouping that linked ALL targets from same YYYYMMDD.
        """
        # Step 1: File-level co-occurrence (observables from SAME log file)
        session_groups: dict[str, list[Observable]] = {}
        for obs in self._all_observables:
            key = obs.source_file
            session_groups.setdefault(key, []).append(obs)

        for source_file, group in session_groups.items():
            unique = {obs.fingerprint: obs for obs in group}
            items = list(unique.values())
            if len(items) > 30:
                continue
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    if a.fingerprint == b.fingerprint:
                        continue
                    self._link_observables(a, b, "co_occurrence_file", 0.4)

        # Step 2: Pipeline-label co-occurrence (same YYYYMMDD_HHMM, NOT just YYYYMMDD)
        pipeline_groups: dict[str, set[str]] = {}
        for m in self._metas:
            fname = Path(m["_source_file"]).name
            ts_match = re.match(r"(\d{8}_\d{4})", fname)
            if ts_match:
                ts_key = ts_match.group(1)  # Full 13-char timestamp (YYYYMMDD_HHMM)
                pipeline_groups.setdefault(ts_key, set()).add(m.get("target", ""))

        for _ts, targets in pipeline_groups.items():
            targets_list = [t for t in targets if t and not _is_garbage_target(t)]
            # Only link if ≤5 targets in same minute (real pipeline run, not mass scan)
            if len(targets_list) > 5:
                continue
            for i, a in enumerate(targets_list):
                for b in targets_list[i + 1:]:
                    if a != b:
                        obs_a = self._find_observable(a)
                        obs_b = self._find_observable(b)
                        if obs_a and obs_b:
                            self._link_observables(obs_a, obs_b, "same_pipeline_run", 0.45)

        # Step 3: Name-matching heuristic
        usernames = [obs for obs in self._all_observables if obs.obs_type == "username"]
        for i, a in enumerate(usernames):
            for b in usernames[i + 1:]:
                if a.fingerprint == b.fingerprint:
                    continue
                if self._names_match(a.value, b.value):
                    self._link_observables(a, b, "name_match", 0.6)

        self.db.commit()

        # Step 4: Assign verification tiers
        self._assign_tiers()

        # Step 5: Transitive closure → clusters
        self.clusters = self._build_clusters()
        return self.clusters

    @staticmethod
    def _names_match(a: str, b: str) -> bool:
        """Check if two usernames are variants of the same name."""
        a_n = a.lower().replace(" ", "").replace("_", "").replace(".", "")
        b_n = b.lower().replace(" ", "").replace("_", "").replace(".", "")
        if not a_n or not b_n:
            return False
        if a_n == b_n:
            return True
        if len(a_n) > 3 and len(b_n) > 3 and (a_n in b_n or b_n in a_n):
            return True
        return False

    def _assign_tiers(self):
        """Assign verification tiers based on evidence quality."""
        for obs in self._all_observables:
            if obs.is_original_target:
                obs.tier = TIER_CONFIRMED
            elif obs.source_tool.startswith("confirmed_import") or any(tool.startswith("confirmed_import") for tool in obs.source_tools):
                obs.tier = TIER_CONFIRMED
            elif len(obs.source_tools) >= 2:
                obs.tier = TIER_CONFIRMED  # Multi-source corroboration
            elif obs.depth == 0:
                obs.tier = TIER_PROBABLE
            else:
                obs.tier = TIER_UNVERIFIED
            self.db.execute(
                "UPDATE observables SET tier = ? WHERE obs_type = ? AND value = ?",
                (obs.tier, obs.obs_type, obs.value),
            )
        self.db.commit()

    def _link_observables(self, a: Observable, b: Observable, reason: str, confidence: float):
        # Ensure consistent ordering
        key_a = (a.obs_type, a.value)
        key_b = (b.obs_type, b.value)
        if key_a > key_b:
            key_a, key_b = key_b, key_a
        self.db.execute(
            "INSERT OR REPLACE INTO entity_links (obs_a_type, obs_a_value, obs_b_type, obs_b_value, link_reason, confidence) "
            "VALUES (?, ?, ?, ?, ?, max(?, coalesce((SELECT confidence FROM entity_links WHERE obs_a_type=? AND obs_a_value=? AND obs_b_type=? AND obs_b_value=?), 0)))",
            (*key_a, *key_b, reason, confidence, *key_a, *key_b),
        )

    def _find_observable(self, value: str) -> Observable | None:
        return self._obs_lookup.get(value)

    def _build_clusters(self) -> list[IdentityCluster]:
        """Union-Find transitive closure over entity_links — tier-aware."""
        nodes: dict[str, str] = {}
        all_obs_map: dict[str, Observable] = {}
        for obs in self._all_observables:
            fp = obs.fingerprint
            nodes[fp] = fp
            all_obs_map[fp] = obs

        def find(x: str) -> str:
            while nodes[x] != x:
                nodes[x] = nodes[nodes[x]]
                x = nodes[x]
            return x

        def union(a: str, b: str):
            ra, rb = find(a), find(b)
            if ra != rb:
                nodes[ra] = rb

        # Only apply links where at least one side is confirmed/probable
        for row in self.db.execute("SELECT obs_a_type, obs_a_value, obs_b_type, obs_b_value, confidence FROM entity_links"):
            fp_a = f"{row[0]}:{row[1]}"
            fp_b = f"{row[2]}:{row[3]}"
            if fp_a in nodes and fp_b in nodes:
                obs_a = all_obs_map.get(fp_a)
                obs_b = all_obs_map.get(fp_b)
                if obs_a and obs_b:
                    a_trusted = obs_a.tier in (TIER_CONFIRMED, TIER_PROBABLE) or obs_a.is_original_target
                    b_trusted = obs_b.tier in (TIER_CONFIRMED, TIER_PROBABLE) or obs_b.is_original_target
                    if a_trusted or b_trusted:
                        union(fp_a, fp_b)

        groups: dict[str, list[Observable]] = {}
        for fp, obs in all_obs_map.items():
            root = find(fp)
            groups.setdefault(root, []).append(obs)

        clusters: list[IdentityCluster] = []
        for root, obs_list in groups.items():
            # Label: prefer confirmed multi-word username, then email, then phone
            label = ""
            usernames = sorted(
                [o.value for o in obs_list if o.obs_type == "username" and o.tier != TIER_UNVERIFIED],
                key=lambda v: (-len(v.split()), -len(v)),
            )
            if not usernames:
                usernames = sorted(
                    [o.value for o in obs_list if o.obs_type == "username"],
                    key=lambda v: (-len(v.split()), -len(v)),
                )
            real_usernames = [
                u for u in usernames
                if len(u) > 3
                and not _HEX_ONLY_RE.fullmatch(u)
                and u.lower() not in ("accounts", "profile", "user.aspx", "search")
            ]
            if real_usernames:
                label = real_usernames[0]
            else:
                for pref in ("email", "phone", "domain"):
                    candidates = [o for o in obs_list if o.obs_type == pref]
                    if candidates:
                        label = candidates[0].value
                        break
            if not label:
                label = obs_list[0].value

            # Collect profile URLs (with ucoz dedup)
            urls: list[str] = []
            seen_platforms: dict[str, str] = {}  # platform -> first URL
            for obs in obs_list:
                if obs.obs_type == "username":
                    rows = self.db.execute(
                        "SELECT url FROM profile_urls WHERE username = ?", (obs.value,)
                    ).fetchall()
                    for r in rows:
                        url = r[0]
                        platform = self._platform_from_url(url)
                        # ucoz dedup: only keep first URL per ucoz platform
                        if platform == "ucoz":
                            if "ucoz" not in seen_platforms:
                                seen_platforms["ucoz"] = url
                                urls.append(url)
                        else:
                            urls.append(url)

            # v2 Confidence: chain-based, NOT linear quantity
            confirmed_count = sum(1 for o in obs_list if o.tier == TIER_CONFIRMED)
            probable_count = sum(1 for o in obs_list if o.tier == TIER_PROBABLE)
            total = len(obs_list)
            if total == 0:
                confidence = 0.0
            else:
                quality_ratio = (confirmed_count * 1.0 + probable_count * 0.5) / total
                source_tools = {obs.source_tool for obs in obs_list}
                tool_bonus = min(0.2, 0.05 * len(source_tools))
                cluster_fingerprints = {obs.fingerprint for obs in obs_list}
                max_link_confidence = 0.0
                for row in self.db.execute(
                    "SELECT obs_a_type, obs_a_value, obs_b_type, obs_b_value, confidence FROM entity_links"
                ):
                    fp_a = f"{row[0]}:{row[1]}"
                    fp_b = f"{row[2]}:{row[3]}"
                    if fp_a in cluster_fingerprints and fp_b in cluster_fingerprints:
                        max_link_confidence = max(max_link_confidence, float(row[4] or 0.0))
                link_bonus = 0.05 if max_link_confidence >= 0.9 else 0.0
                confidence = min(0.95, quality_ratio * 0.7 + tool_bonus + link_bonus + 0.1)

            source_tools_set = {obs.source_tool for obs in obs_list}
            cluster = IdentityCluster(
                person_id=str(uuid.uuid4()),
                label=label,
                observables=obs_list,
                profile_urls=sorted(set(urls)),
                confidence=confidence,
                sources=source_tools_set,
            )
            clusters.append(cluster)

        clusters.sort(key=lambda c: (sum(1 for o in c.observables if o.tier == TIER_CONFIRMED), len(c.observables)), reverse=True)
        return clusters

    # ── 3.  Discovery Queue ───────────────────────────────────────

    def get_pivot_queue(self) -> list[dict[str, Any]]:
        """Return observables needing further investigation with reasons."""
        existing_targets = {m.get("target", "") for m in self._metas}
        queue: list[dict[str, Any]] = []

        # Unverified observables need cross-tool checks
        for obs in self._all_observables:
            if obs.tier == TIER_UNVERIFIED and obs.value not in existing_targets:
                suggested, reason = self._suggest_tools_with_reason(obs)
                if suggested:
                    queue.append({
                        "obs_type": obs.obs_type,
                        "value": obs.value,
                        "discovered_by": obs.source_tool,
                        "depth": obs.depth,
                        "suggested_tools": suggested,
                        "reason": reason,
                        "tier": obs.tier,
                    })
                    self.db.execute(
                        "INSERT OR IGNORE INTO discovery_queue (obs_type, value, suggested_tools, reason, depth) VALUES (?, ?, ?, ?, ?)",
                        (obs.obs_type, obs.value, json.dumps(suggested), reason, obs.depth),
                    )

        # Suggest reverse-lookup for phones without name confirmation
        for obs in self._all_observables:
            if obs.obs_type == "phone" and obs.is_original_target:
                linked_usernames = [
                    o for o in self._all_observables
                    if o.obs_type == "username" and o.tier == TIER_CONFIRMED
                ]
                if not linked_usernames:
                    queue.append({
                        "obs_type": obs.obs_type,
                        "value": obs.value,
                        "discovered_by": obs.source_tool,
                        "depth": 0,
                        "suggested_tools": ["GetContact", "TrueCaller"],
                        "reason": "Phone has no name confirmation — needs reverse lookup",
                        "tier": obs.tier,
                    })

        self.db.commit()
        return queue

    @staticmethod
    def _suggest_tools_with_reason(obs: Observable) -> tuple[list[str], str]:
        if obs.obs_type == "phone":
            return ["phoneinfoga", "GetContact"], "Phone found by single tool — needs cross-validation"
        if obs.obs_type == "email":
            return ["holehe", "h8mail"], "Email needs breach/registration check"
        if obs.obs_type == "username":
            return ["sherlock", "maigret"], "Username needs profile enumeration"
        if obs.obs_type == "domain":
            return ["theHarvester", "whois"], "Domain needs WHOIS + subdomain enumeration"
        return [], ""

    # ── 4.  Profile Verification ─────────────────────────────────

    def verify_profiles(self, max_checks: int = 50, timeout: float = 5.0, proxy: str | None = None):
        return self.verifier.verify_profiles(max_checks=max_checks, timeout=timeout, proxy=proxy)

    def reverify_expired(self, max_checks: int = 50, timeout: float = 5.0, proxy: str | None = None) -> dict[str, int]:
        return self.verifier.reverify_expired(max_checks=max_checks, timeout=timeout, proxy=proxy)

    def get_profile_stats(self) -> dict[str, int]:
        return self.verifier.get_profile_stats()

    # ── 4a. Content Verification ──────────────────────────────────

    def verify_content(self, max_checks: int = 100, timeout: float = 8.0, proxy: str | None = None) -> dict[str, int]:
        return self.verifier.verify_content(max_checks=max_checks, timeout=timeout, proxy=proxy)

        # Gather all known name tokens from confirmed observables
        name_tokens: set[str] = set()
        for obs in self._all_observables:
            if obs.obs_type == "username" and obs.tier == TIER_CONFIRMED:
                name_tokens.add(obs.value.lower())
                for part in obs.value.lower().split():
                    if len(part) >= 3:
                        name_tokens.add(part)
            if obs.obs_type == "phone":
                name_tokens.add(obs.value)
        # Always include cluster labels
        for cluster in self.clusters:
            for part in cluster.label.lower().split():
                if len(part) >= 3:
                    name_tokens.add(part)

        # Negative indicators — page says profile doesn't exist
        _NOT_FOUND_PATTERNS = [
            "not found", "no results", "404", "page not found",
            "user not found", "пользователь не найден",
            "не найдено", "нет результатов", "сторінку не знайдено",
            "hasn't posted", "no posts", "no activity",
            "this user doesn't exist", "could not be found",
            "no matches", "ничего не найдено",
        ]

        counts = {"upgraded": 0, "killed": 0, "unchanged": 0, "errors": 0, "skipped_blacklisted": 0}

        def _check_content(row):
            url_id, url, username = row[0], row[1], row[2]

            # Skip blacklisted platforms (already soft_match, keep them)
            platform = DiscoveryEngine._platform_from_url(url)
            if platform in _FALSE_POSITIVE_PLATFORMS:
                return (url_id, "skip_blacklisted")

            try:
                status_code, _headers, body = proxy_aware_request(
                    url,
                    method="GET",
                    timeout=timeout,
                    proxy=proxy,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "uk,en;q=0.5",
                    },
                    max_body_bytes=MAX_BODY_BYTES,
                )

                if status_code >= 400 or status_code == 0:
                    return (url_id, "dead")

                body_lower = body.lower()

                # Check for negative indicators first
                for neg in _NOT_FOUND_PATTERNS:
                    if neg in body_lower:
                        return (url_id, "dead")

                # Check for name token presence in body
                name_hits = sum(1 for tok in name_tokens if tok in body_lower)
                if name_hits >= 2:
                    return (url_id, "verified")

                return (url_id, "soft_match")  # ambiguous — keep

            except Exception:
                return (url_id, "error")

        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as executor:
            futures = {executor.submit(_check_content, r): r for r in rows}
            for future in as_completed(futures):
                url_id, result = future.result()
                if result == "skip_blacklisted":
                    counts["skipped_blacklisted"] += 1
                elif result == "error":
                    counts["errors"] += 1
                elif result == "verified":
                    counts["upgraded"] += 1
                    self.db.execute(
                        "UPDATE profile_urls SET status = 'verified', content_match = 1, "
                        "checked_at = datetime('now') WHERE id = ?",
                        (url_id,),
                    )
                elif result == "dead":
                    counts["killed"] += 1
                    self.db.execute(
                        "UPDATE profile_urls SET status = 'dead', checked_at = datetime('now') WHERE id = ?",
                        (url_id,),
                    )
                else:
                    counts["unchanged"] += 1

        self.db.commit()
        return counts

    # ── 4b. Deep Recon Integration ────────────────────────────────

    def run_deep_recon(
        self,
        target_name: str | None = None,
        modules: list[str] | None = None,
        proxy: str | None = None,
        leak_dir: str | None = None,
        known_phones_override: list[str] | None = None,
        known_usernames_override: list[str] | None = None,
    ) -> tuple[dict[str, Any], ReconReport | None]:
        """
        Run deep UA+RU recon and feed results back into the observable pipeline.

        Args:
            target_name: Override auto-detected name (from primary cluster label)
            modules: List of module names or preset (e.g. "deep-all")
            proxy: SOCKS5 proxy URL (e.g. "socks5h://127.0.0.1:9050")
            leak_dir: Override default leak scan directory
            known_phones_override: Extra known phones to inject for this run
            known_usernames_override: Extra known usernames to inject for this run

                Returns:
                        Tuple of:
                            - summary dict with counts of new observables added
                            - ReconReport (or None when target is missing)
        """
        from deep_recon import DeepReconRunner, ReconReport

        # Auto-detect target name from primary cluster
        if not target_name and self.clusters:
            target_name = self.clusters[0].label
        if not target_name:
            return ({"error": "No target name — run resolve_entities() first or pass target_name"}, None)

        # Collect known phones and usernames from current state
        known_phones = [
            obs.value for obs in self._all_observables
            if obs.obs_type == "phone"
        ]
        known_usernames = [
            obs.value for obs in self._all_observables
            if obs.obs_type == "username"
        ]

        if known_phones_override:
            known_phones.extend(p.strip() for p in known_phones_override if p and p.strip())
            known_phones = sorted(set(known_phones))
        if known_usernames_override:
            known_usernames.extend(u.strip() for u in known_usernames_override if u and u.strip())
            known_usernames = sorted(set(known_usernames))

        print(f"\n{'='*60}")
        print(f"DEEP RECON: {target_name}")
        print(f"Known phones: {known_phones}")
        print(f"Known usernames: {known_usernames}")
        print(f"Modules: {modules or 'all'}")
        print(f"Proxy: {proxy or 'direct'}")
        if leak_dir:
            print(f"Leak dir: {leak_dir}")
        print(f"{'='*60}\n")

        runner = DeepReconRunner(proxy=proxy, leak_dir=leak_dir)
        report = runner.run(
            target_name=target_name,
            known_phones=known_phones,
            known_usernames=known_usernames,
            modules=modules,
        )

        # Feed hits back into the discovery engine
        new_obs_count = 0
        for hit in report.hits:
            if hit.confidence <= 0:
                continue  # skip manual-check placeholders

            obs = self._classify_and_register(
                value=hit.value,
                source_tool=f"deep_recon:{hit.source_module}",
                source_target=target_name,
                source_file=f"deep_recon:{hit.source_detail}",
                depth=1,
                commit=False,
            )
            if obs:
                new_obs_count += 1
                # Add to pivot queue with reason
                self.db.execute(
                    "INSERT OR IGNORE INTO discovery_queue "
                    "(obs_type, value, suggested_tools, reason, depth, state) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        hit.observable_type,
                        hit.value,
                        json.dumps(["cross_verify", "getcontact"]),
                        f"Found by {hit.source_module} (conf={hit.confidence:.0%}): {hit.source_detail}",
                        1,
                        "pending",
                    ),
                )

        self.db.commit()

        # Print summary
        summary = DeepReconRunner.report_summary(report)
        print(summary)

        outcome_payload = [outcome.to_dict() for outcome in report.outcomes]
        summary_errors = [
            entry
            for entry in (outcome.to_error_dict() for outcome in report.outcomes)
            if entry
        ]
        summary_modules = [outcome.module_name for outcome in report.outcomes] or list(report.modules_run)

        return ({
            "target": target_name,
            "modules_run": summary_modules,
            "total_hits": len(report.hits),
            "new_observables": new_obs_count,
            "new_phones": report.new_phones,
            "new_emails": report.new_emails,
            "cross_confirmed": len(report.cross_confirmed),
            "outcomes": outcome_payload,
            "errors": summary_errors,
        }, report)

    # ── 5.  Reporting ─────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        obs_count = self.db.execute("SELECT COUNT(*) FROM observables").fetchone()[0]
        rejected_count = self.db.execute("SELECT COUNT(*) FROM rejected_targets").fetchone()[0]
        link_count = self.db.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]
        url_count = self.db.execute("SELECT COUNT(*) FROM profile_urls").fetchone()[0]
        queue_count = self.db.execute("SELECT COUNT(*) FROM discovery_queue WHERE state='pending'").fetchone()[0]
        confirmed = sum(1 for o in self._all_observables if o.tier == TIER_CONFIRMED)
        probable = sum(1 for o in self._all_observables if o.tier == TIER_PROBABLE)
        unverified = sum(1 for o in self._all_observables if o.tier == TIER_UNVERIFIED)
        profile_stats = self.get_profile_stats()
        return {
            "total_metadata_files": len(self._metas),
            "total_observables": obs_count,
            "confirmed_observables": confirmed,
            "probable_observables": probable,
            "unverified_observables": unverified,
            "rejected_targets": rejected_count,
            "entity_links": link_count,
            "profile_urls": url_count,
            "profile_verification": profile_stats,
            "identity_clusters": len(self.clusters),
            "pending_pivots": queue_count,
            "tool_stats": self._tool_stats,
        }

    def _get_runs_dir(self) -> Path:
        db_list = self.db.execute("PRAGMA database_list").fetchall()
        for row in db_list:
            db_file = row[2]
            if db_file:
                return Path(db_file).resolve().parent
        return RUNS_ROOT

    @staticmethod
    def _get_lane_registry() -> dict[str, str]:
        from registry import MODULE_LANE
        return dict(MODULE_LANE)

    @staticmethod
    def _lane_from_source_tool(source_tool: str, lane_registry: dict[str, str]) -> str | None:
        if not source_tool:
            return None
        module_name = source_tool.split(":", 1)[1] if source_tool.startswith("deep_recon:") else source_tool
        return lane_registry.get(module_name)

    def _load_latest_deep_recon_report(self) -> dict[str, Any] | None:
        runs_dir = self._get_runs_dir()
        candidates = sorted(runs_dir.glob("deep_recon_*.json"))
        if not candidates:
            return None

        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        payload["_path"] = str(latest)
        return payload

    def _build_lane_summary(self, primary: IdentityCluster | None) -> dict[str, Any]:
        lane_registry = self._get_lane_registry()
        latest_report = self._load_latest_deep_recon_report()
        summary: dict[str, Any] = {
            "artifact": latest_report,
            "fast": {
                "label": "Fast Lane",
                "modules_run": [],
                "hits": [],
                "errors": [],
                "observables": [],
            },
            "slow": {
                "label": "Slow Lane",
                "modules_run": [],
                "hits": [],
                "errors": [],
                "observables": [],
            },
        }

        if latest_report:
            for module_name in latest_report.get("modules", []):
                lane_name = lane_registry.get(module_name)
                if lane_name in summary:
                    summary[lane_name]["modules_run"].append(module_name)

            for hit in latest_report.get("hits", []):
                lane_name = lane_registry.get(str(hit.get("source", "")))
                if lane_name in summary:
                    summary[lane_name]["hits"].append(hit)

            for error in latest_report.get("errors", []):
                lane_name = lane_registry.get(str(error.get("module", "")))
                if lane_name in summary:
                    summary[lane_name]["errors"].append(error)

        seen_obs: set[tuple[str, str, str]] = set()
        observable_rows = self.db.execute(
            "SELECT obs_type, value, tier, source_tool FROM observables WHERE source_tool LIKE 'deep_recon:%'"
        ).fetchall()
        for row in observable_rows:
            lane_name = self._lane_from_source_tool(str(row[3]), lane_registry)
            if lane_name not in ("fast", "slow"):
                continue
            obs_key = (lane_name, str(row[0]), str(row[1]))
            if obs_key in seen_obs:
                continue
            seen_obs.add(obs_key)
            summary[lane_name]["observables"].append({
                "type": str(row[0]),
                "value": str(row[1]),
                "tier": str(row[2]),
                "source_tool": str(row[3]),
            })

        return summary

    @staticmethod
    def _mask_middle(value: str, keep_start: int = 1, keep_end: int = 1, mask_char: str = "*") -> str:
        if not value:
            return value
        if len(value) <= keep_start + keep_end:
            return mask_char * len(value)
        return value[:keep_start] + (mask_char * (len(value) - keep_start - keep_end)) + value[-keep_end:]

    @classmethod
    def _redact_domain(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        domain = value.strip().lower()
        labels = [label for label in domain.split(".") if label]
        if len(labels) < 2:
            return cls._mask_middle(domain, keep_start=1, keep_end=0)
        masked_labels = [cls._mask_middle(label, keep_start=1, keep_end=0) for label in labels[:-1]]
        masked_labels.append(labels[-1])
        return ".".join(masked_labels)

    @classmethod
    def _redact_phone(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        prefix_len = 4 if value.startswith("+") else 2
        suffix_len = 2 if mode == "shareable" else 0
        return cls._mask_middle(value, keep_start=prefix_len, keep_end=suffix_len)

    @classmethod
    def _redact_email(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        if "@" not in value:
            return cls._mask_middle(value, keep_start=1, keep_end=0)
        local_part, domain = value.split("@", 1)
        masked_local = cls._mask_middle(local_part, keep_start=1, keep_end=0)
        return f"{masked_local}@{cls._redact_domain(domain, mode)}"

    @classmethod
    def _redact_username(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        if mode == "strict":
            return cls._mask_middle(value, keep_start=1, keep_end=0)
        return cls._mask_middle(value, keep_start=2, keep_end=1)

    @classmethod
    def _redact_generic_text(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        parts = re.split(r"(\s+)", value)
        masked: list[str] = []
        for part in parts:
            if not part or part.isspace():
                masked.append(part)
                continue
            masked.append(cls._mask_middle(part, keep_start=1, keep_end=0 if mode == "strict" else 1))
        return "".join(masked)

    @classmethod
    def _redact_url(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        parsed = urlparse(value)
        host = parsed.hostname or parsed.netloc or value
        masked_host = cls._redact_domain(host, mode)
        path = parsed.path.strip("/")
        if not path:
            return f"{parsed.scheme}://{masked_host}" if parsed.scheme else masked_host
        first_segment = path.split("/", 1)[0]
        masked_segment = cls._mask_middle(first_segment, keep_start=1, keep_end=0)
        suffix = "/..." if "/" in path else ""
        if parsed.scheme:
            return f"{parsed.scheme}://{masked_host}/{masked_segment}{suffix}"
        return f"{masked_host}/{masked_segment}{suffix}"

    def _redact_value(self, value: str, obs_type: str | None = None, mode: str = "shareable") -> str:
        if mode == "internal" or not value:
            return value
        inferred = obs_type or self._infer_type(value) or "text"
        if inferred == "phone":
            return self._redact_phone(value, mode)
        if inferred == "email":
            return self._redact_email(value, mode)
        if inferred == "domain":
            return self._redact_domain(value, mode)
        if inferred == "url":
            return self._redact_url(value, mode)
        if inferred == "username":
            return self._redact_username(value, mode)
        return self._redact_generic_text(value, mode)

    def render_graph_report(self, output_path: str | Path | None = None, redaction_mode: str = "shareable") -> str:
        return self.renderer.render_graph_report(output_path=output_path, redaction_mode=redaction_mode)
        r'''
            obs_by_type: dict[str, list[str]] = {}
            for obs in primary.observables:
                obs_by_type.setdefault(obs.obs_type, []).append(obs.value)

            confirmed_obs = [o for o in primary.observables if o.tier == TIER_CONFIRMED]
            probable_obs = [o for o in primary.observables if o.tier == TIER_PROBABLE]
            unverified_obs = [o for o in primary.observables if o.tier == TIER_UNVERIFIED]

            summary_parts = [f"<strong>Primary Identity:</strong> {esc(self._redact_value(primary.label, mode=redaction_mode))}"]
            if "phone" in obs_by_type:
                summary_parts.append(f"<strong>Phone(s):</strong> {', '.join(esc(self._redact_value(p, 'phone', redaction_mode)) for p in sorted(set(obs_by_type['phone'])))}")
            if "email" in obs_by_type:
                summary_parts.append(f"<strong>Email(s):</strong> {', '.join(esc(self._redact_value(e, 'email', redaction_mode)) for e in sorted(set(obs_by_type['email'])))}")
            if "username" in obs_by_type:
                summary_parts.append(f"<strong>Username(s):</strong> {', '.join(esc(self._redact_value(u, 'username', redaction_mode)) for u in sorted(set(obs_by_type['username'])))}")
            if "domain" in obs_by_type:
                domains = [d for d in sorted(set(obs_by_type["domain"])) if d.lower() not in _PLACEHOLDER_DOMAINS]
                if domains:
                    summary_parts.append(f"<strong>Domain(s):</strong> {', '.join(esc(self._redact_value(d, 'domain', redaction_mode)) for d in domains)}")
            summary_parts.append(
                f"<strong>Cluster confidence:</strong> {primary.confidence:.0%} "
                f"({len(confirmed_obs)} confirmed, {len(probable_obs)} probable, {len(unverified_obs)} unverified)"
            )
            summary_parts.append(
                f"<strong>Social profiles found:</strong> {len(primary.profile_urls)}"
            )
            if self._confirmed_imports:
                import_total = sum(item["imported"] for item in self._confirmed_imports)
                import_labels = ", ".join(item["label"] for item in self._confirmed_imports)
                summary_parts.append(
                    f"<strong>Confirmed evidence injected:</strong> {import_total} via {esc(import_labels)}"
                )
        else:
            summary_parts = ["No identity clusters resolved."]
            confirmed_obs = []
            probable_obs = []
            unverified_obs = []

        summary_html = "".join(f"<p>{p}</p>" for p in summary_parts)

        # Tool coverage
        tool_badges = ""
        for tool, ts in sorted(self._tool_stats.items()):
            total = ts["success"] + ts["failed"]
            css_class = "badge-ok" if ts["failed"] == 0 else "badge-warn"
            tool_badges += f"<span class='badge {css_class}'>{esc(tool)}: {ts['success']}/{total} OK, {ts['observables']} obs</span> "

        lane_summary = self._build_lane_summary(primary)
        lane_cards_html = ""
        lane_artifact = lane_summary.get("artifact")
        lane_source_note = ""
        if lane_artifact:
            lane_source_note = (
                f"Latest deep recon artifact: <span class='mono'>{esc(Path(str(lane_artifact['_path'])).name)}</span> "
                f"({esc(str(lane_artifact.get('started', 'n/a')))} → {esc(str(lane_artifact.get('finished', 'n/a')))})"
            )

        for lane_name in ("fast", "slow"):
            lane_data = lane_summary[lane_name]
            modules_run = sorted(set(lane_data["modules_run"]))
            evidence_modules = sorted({
                item["source_tool"].split(":", 1)[1]
                for item in lane_data["observables"]
                if item.get("source_tool", "").startswith("deep_recon:")
            })
            if modules_run:
                module_badges = " ".join(
                    f"<span class='badge badge-lane-module'>{esc(module_name)}</span>" for module_name in modules_run
                )
            elif evidence_modules:
                module_badges = (
                    "<span class='hint'>Historical evidence modules:</span> "
                    + " ".join(
                        f"<span class='badge badge-lane-module'>{esc(module_name)}</span>" for module_name in evidence_modules
                    )
                )
            else:
                module_badges = "<span class='hint'>No modules recorded in latest artifact.</span>"

            confirmed_count = sum(1 for obs in lane_data["observables"] if obs["tier"] in (TIER_CONFIRMED, TIER_PROBABLE))
            rejected_count = sum(1 for obs in lane_data["observables"] if obs["tier"] == "rejected")
            dead_end_count = sum(1 for obs in lane_data["observables"] if obs["tier"] not in (TIER_CONFIRMED, TIER_PROBABLE, "rejected"))
            lane_title_meta = (
                "<div class='lane-snr'>"
                f"<span class='lane-snr-badge lane-snr-confirmed' title='Confirmed: corroborated or validated evidence ready for analyst attention.'>{confirmed_count} confirmed</span>"
                f"<span class='lane-snr-badge lane-snr-rejected' title='Rejected: filtered false positives, such as platform artefacts or invalid profile hits.'>{rejected_count} rejected</span>"
                f"<span class='lane-snr-badge lane-snr-dead' title='Dead-end: leads that did not confirm and currently terminate without escalation.'>{dead_end_count} dead-end</span>"
                "</div>"
            )

            highlights_html = ""
            if lane_name == "slow" and lane_data["observables"]:
                confirmed_obs = [
                    obs for obs in lane_data["observables"]
                    if obs["tier"] in (TIER_CONFIRMED, TIER_PROBABLE)
                ]
                dead_end_obs = [
                    obs for obs in lane_data["observables"]
                    if obs["tier"] not in (TIER_CONFIRMED, TIER_PROBABLE)
                ]

                confirmed_items = "".join(
                    f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> "
                    f"<code>{esc(self._redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span> "
                    f"<span class='hint'>via {esc(obs['source_tool'])}</span></li>"
                    for obs in confirmed_obs[:8]
                ) or "<li class='hint'>No confirmed slow-lane evidence registered yet.</li>"

                dead_end_items = "".join(
                    f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> "
                    f"<code>{esc(self._redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span> "
                    f"<span class='hint'>via {esc(obs['source_tool'])}</span></li>"
                    for obs in dead_end_obs[:12]
                )

                dead_end_block = ""
                if dead_end_items:
                    dead_end_block = (
                        "<details class='lane-dead-ends'><summary>Rejected / Dead Ends ("
                        + str(len(dead_end_obs))
                        + ")</summary><ul class='lane-muted-list'>"
                        + dead_end_items
                        + "</ul></details>"
                    )

                highlights_html = (
                    "<div class='lane-evidence-block lane-evidence-confirmed'><strong>Confirmed Evidence:</strong>"
                    "<ul>" + confirmed_items + "</ul></div>"
                    + dead_end_block
                )
            else:
                highlights: list[str] = []
                seen_highlights: set[tuple[str, str]] = set()
                sorted_hits = sorted(
                    lane_data["hits"],
                    key=lambda item: (float(item.get("confidence", 0.0)), str(item.get("value", ""))),
                    reverse=True,
                )
                for hit in sorted_hits:
                    hit_key = (str(hit.get("type", "")), str(hit.get("value", "")))
                    if hit_key in seen_highlights:
                        continue
                    seen_highlights.add(hit_key)
                    confidence = float(hit.get("confidence", 0.0) or 0.0)
                    confidence_label = "pending manual check" if confidence <= 0 else f"{confidence:.0%} confidence"
                    detail = str(hit.get("detail", ""))[:90]
                    highlights.append(
                        f"<li><span class='badge badge-{esc(str(hit.get('type', 'url')))}'>{esc(str(hit.get('type', 'signal')))}</span> "
                        f"<code>{esc(self._redact_value(str(hit.get('value', '')), str(hit.get('type', 'url')), redaction_mode))}</code> <span class='hint'>[{esc(confidence_label)} · {esc(self._redact_value(detail, mode=redaction_mode))}]</span></li>"
                    )
                    if len(highlights) >= 6:
                        break

                if not highlights:
                    sorted_obs = sorted(
                        lane_data["observables"],
                        key=lambda item: (item["tier"], item["type"], item["value"]),
                    )
                    for obs in sorted_obs[:6]:
                        highlights.append(
                            f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> "
                            f"<code>{esc(self._redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span></li>"
                        )

                if not highlights:
                    highlights.append("<li class='hint'>No lane-correlated findings registered in this dossier.</li>")
                highlights_html = f"<strong>Highlights:</strong><ul>{''.join(highlights)}</ul>"

            error_html = ""
            if lane_data["errors"]:
                error_items = "".join(
                    f"<li><code>{esc(str(err.get('module', 'unknown')))}</code> <span class='hint'>{esc(str(err.get('error', 'error')))}</span></li>"
                    for err in lane_data["errors"][:5]
                )
                error_html = f"<div class='lane-errors'><strong>Execution faults:</strong><ul>{error_items}</ul></div>"

            lane_cards_html += (
                f"<div class='lane-card lane-{lane_name}'>"
                f"<div class='lane-head'><div><h3>{esc(lane_data['label'])}</h3>"
                f"{lane_title_meta}"
                f"<p class='hint'>{'Hot-path pivots, low-noise surface acquisition.' if lane_name == 'fast' else 'Deep infrastructure, archive, and wide-network enumeration.'}</p></div>"
                f"<div class='lane-metrics'><span><strong>{len(modules_run)}</strong> modules</span><span><strong>{len(lane_data['hits'])}</strong> raw hits</span><span><strong>{len(lane_data['observables'])}</strong> dossier observables</span><span><strong>{len(lane_data['errors'])}</strong> faults</span></div></div>"
                f"<div class='lane-modules'><strong>Modules run:</strong> {module_badges}</div>"
                f"<div class='lane-highlights'>{highlights_html}</div>"
                f"{error_html}"
                f"</div>"
            )

        # ── Entity graph nodes — with tier badges ──
        graph_nodes_html = ""
        graph_edges_html = ""
        if primary:
            seen_values: set[str] = set()
            for obs in primary.observables:
                if obs.value in seen_values:
                    continue
                seen_values.add(obs.value)
                icon = {"phone": "\U0001f4f1", "email": "\U0001f4e7", "username": "\U0001f464", "domain": "\U0001f310", "url": "\U0001f517"}.get(obs.obs_type, "\U0001f4cc")
                tier_css = {"confirmed": "tier-confirmed", "probable": "tier-probable", "unverified": "tier-unverified"}.get(obs.tier, "")
                tier_label = obs.tier.upper()
                graph_nodes_html += (
                    f"<div class='gnode gnode-{esc(obs.obs_type)} {tier_css}'>"
                    f"{icon} {esc(self._redact_value(obs.value, obs.obs_type, redaction_mode))} <span class='tier-badge {tier_css}'>{tier_label}</span>"
                    f"</div>\n"
                )

            edges = self.db.execute(
                "SELECT obs_a_type, obs_a_value, obs_b_type, obs_b_value, link_reason, confidence FROM entity_links ORDER BY confidence DESC"
            ).fetchall()
            primary_fps = {obs.fingerprint for obs in primary.observables}
            for e in edges:
                fp_a = f"{e[0]}:{e[1]}"
                fp_b = f"{e[2]}:{e[3]}"
                if fp_a in primary_fps and fp_b in primary_fps:
                    reason = str(e[4]).replace("_", " ")
                    graph_edges_html += f"<tr><td>{esc(self._redact_value(e[1], e[0], redaction_mode))}</td><td class='edge-reason'>{esc(reason)}</td><td>{esc(self._redact_value(e[3], e[2], redaction_mode))}</td><td>{e[5]:.0%}</td></tr>\n"

        # ── Profile URLs table — with verification status ──
        profile_rows_html = ""
        if primary:
            for url in primary.profile_urls[:50]:
                platform = self._platform_from_url(url)
                status_row = self.db.execute("SELECT status FROM profile_urls WHERE url = ?", (url,)).fetchone()
                url_status = status_row[0] if status_row else "unchecked"
                status_badge = {
                    "verified": "<span class='badge badge-ok'>VERIFIED</span>",
                    "soft_match": "<span class='badge badge-warn'>SOFT</span>",
                    "dead": "<span class='badge badge-dead'>DEAD</span>",
                    "unchecked": "<span class='badge'>UNCHECKED</span>",
                }.get(url_status, "")
                redacted_url = self._redact_value(url, 'url', redaction_mode)
                if redaction_mode == 'internal':
                    profile_cell = f"<a href='{esc(url)}'>{esc(redacted_url)}</a>"
                else:
                    profile_cell = f"<code>{esc(redacted_url)}</code>"
                profile_rows_html += f"<tr><td class='platform'>{esc(platform)}</td><td>{profile_cell}</td><td>{status_badge}</td></tr>\n"

        # ── Pivot queue — with reasons ──
        pivot_rows_html = ""
        for item in pivot_queue[:30]:
            tools = ", ".join(item["suggested_tools"])
            otype = item["obs_type"]
            val = item["value"]
            reason = item.get("reason", "")
            tier = item.get("tier", "")
            pivot_rows_html += (
                f"<tr><td><span class='badge badge-{esc(otype)}'>{esc(otype)}</span></td>"
                f"<td><code>{esc(self._redact_value(val, otype, redaction_mode))}</code></td><td>{esc(tools)}</td>"
                f"<td>{esc(self._redact_value(reason, mode=redaction_mode))}</td><td><span class='tier-badge tier-{esc(tier)}'>{esc(tier.upper() if tier else '')}</span></td></tr>\n"
            )

        # Rejected targets
        rejected_rows = self.db.execute("SELECT raw_target, reason, source_file FROM rejected_targets LIMIT 20").fetchall()
        rejected_html = ""
        for r in rejected_rows:
            rejected_html += f"<tr><td><code>{esc(self._redact_value(strip_ansi(r[0][:80]), mode=redaction_mode))}</code></td><td>{esc(r[1])}</td><td class='mono'>{esc(Path(r[2]).name)}</td></tr>\n"

        # Secondary clusters
        secondary_html = ""
        for cluster in self.clusters[1:]:
            obs_summary = ", ".join(sorted({self._redact_value(obs.value, obs.obs_type, redaction_mode) for obs in cluster.observables}))
            secondary_html += f"<tr><td>{esc(self._redact_value(cluster.label, mode=redaction_mode))}</td><td>{len(cluster.observables)}</td><td>{cluster.confidence:.0%}</td><td class='mono'>{esc(obs_summary[:120])}</td></tr>\n"

        # ── All observables table — with tier column ──
        all_obs_rows = self.db.execute(
            "SELECT obs_type, value, source_tool, source_target, depth, tier FROM observables ORDER BY "
            "CASE tier WHEN 'confirmed' THEN 0 WHEN 'probable' THEN 1 ELSE 2 END, obs_type, value"
        ).fetchall()
        obs_table_html = ""
        for row in all_obs_rows[:100]:
            tier_val = row[5] if len(row) > 5 else "unverified"
            obs_table_html += (
                f"<tr><td><span class='badge badge-{esc(row[0])}'>{esc(row[0])}</span></td>"
                f"<td><code>{esc(self._redact_value(row[1], row[0], redaction_mode))}</code></td><td>{esc(row[2])}</td>"
                f"<td>{esc(self._redact_value(str(row[3])[:30], mode=redaction_mode))}</td><td>{row[4]}</td>"
                f"<td><span class='tier-badge tier-{esc(tier_val)}'>{esc(tier_val.upper())}</span></td></tr>\n"
            )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Emoji section headers (can't use \U escapes inside f-strings)
        _E = {
            "summary": "\U0001f4cb",
            "anchor": "\U0001f3af",
            "link": "\U0001f517",
            "globe": "\U0001f310",
            "pivot": "\U0001f504",
            "chart": "\U0001f4ca",
            "people": "\U0001f465",
            "reject": "\U0001f6ab",
        }

        # Pre-build conditional HTML sections (f-strings can't contain backslashes)
        secondary_section = ""
        if len(self.clusters) > 1:
            secondary_section = (
                "<section class='section'><h2>" + _E["people"] + " Secondary Clusters ("
                + str(len(self.clusters) - 1) + ")</h2><div class='pad'><table><tr><th>Label</th>"
                "<th>Observables</th><th>Confidence</th><th>Values</th></tr>"
                + secondary_html + "</table></div></section>"
            )

        rejected_section = ""
        if rejected_html:
            rejected_section = (
                "<section class='section'><h2>" + _E["reject"] + " Rejected Targets ("
                + str(stats['rejected_targets']) + ")</h2><div class='pad'><p class='hint'>"
                "Filtered by input validation: garbage strings, SHA hashes used as targets, "
                "profile-target type mismatches, placeholder domains, high-entropy tokens."
                "</p><table><tr><th>Raw Target</th><th>Reason</th><th>Source</th></tr>"
                + rejected_html + "</table></div></section>"
            )

        anchor_section = "<p>No identity resolved.</p>"
        if primary:
            anchor_section = (
                "<div class='identity-anchor'><div class='name'>"
                + esc(self._redact_value(primary.label, mode=redaction_mode)) + "</div><div class='sub'>Person ID: <code>"
                + esc(primary.person_id[:12]) + "...</code> "
                + "Confidence: " + f"{primary.confidence:.0%}" + " "
                + str(len(confirmed_obs)) + " confirmed, "
                + str(len(probable_obs)) + " probable, "
                + str(len(unverified_obs)) + " unverified</div></div>"
            )

        page = f"""<!doctype html>
<html lang='uk'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Gonzo Evidence Pack v3.0.2 — {esc(self._redact_value(primary.label, mode=redaction_mode) if primary else 'Unknown')}</title>
<style>
:root {{--bg:#f1f4f3;--card:#fff;--border:#d3dbd6;--accent:#1a6b56;--accent2:#112b45;--text:#171f2b;--muted:#5c6e64;--red:#b84c2e;--green:#2a7d3f;--yellow:#b8860b;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:'Segoe UI','Noto Sans',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.55}}
.wrap{{max-width:1280px;margin:0 auto;padding:24px 20px 60px}}
.hero{{background:linear-gradient(135deg,var(--accent2),var(--accent) 65%,#99622d);color:#fff;border-radius:18px;padding:28px 26px}}
.hero h1{{margin:0;font-size:24px;letter-spacing:.5px}}
.hero-sub{{opacity:.85;font-size:13px;margin:4px 0 0}}
.hero-grid{{display:grid;grid-template-columns:1.4fr .6fr;gap:14px;align-items:start}}
.hero-meta{{text-align:right;font-size:12px;opacity:.8}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:10px;margin-top:16px}}
.card{{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:10px;text-align:center}}
.card .k{{font-size:10px;text-transform:uppercase;opacity:.72}}
.card .v{{font-size:24px;font-weight:800;margin-top:1px}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:14px;margin-top:14px;overflow:hidden}}
.section h2{{margin:0;padding:12px 16px;background:#eaf2ed;border-bottom:1px solid var(--border);font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:var(--accent2)}}
.pad{{padding:14px 16px}}
.exec p{{margin:4px 0;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}}
th{{background:#f4f7f5;font-weight:600;font-size:11px;text-transform:uppercase;color:var(--muted)}}
code{{background:#e8ecea;padding:1px 5px;border-radius:4px;font-size:12px}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all}}
a{{color:var(--accent)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:7px;font-size:11px;font-weight:600;margin:1px 3px 1px 0;background:#e0ede7;color:var(--accent2)}}
.badge-phone{{background:#dde8f7;color:#1a3a6b}}.badge-email{{background:#f0e6fa;color:#5a2d82}}.badge-username{{background:#e6f0e8;color:#1a5a2e}}.badge-domain{{background:#fce6d5;color:#7a3d1a}}.badge-url{{background:#f5f5dc;color:#444}}.badge-ok{{background:#d4edda;color:var(--green)}}.badge-warn{{background:#fff3cd;color:#856404}}.badge-dead{{background:#f8d7da;color:var(--red)}}
.platform{{font-weight:600;color:var(--accent);text-transform:capitalize}}
.edge-reason{{font-style:italic;color:var(--muted)}}
details{{margin-bottom:6px}} summary{{cursor:pointer;font-weight:600;padding:3px 0}}
.hint{{color:var(--muted);font-size:12px}}
.graph-grid{{display:flex;flex-wrap:wrap;gap:8px;padding:8px 0}}
.gnode{{padding:8px 14px;border-radius:10px;font-size:13px;font-weight:500;border:2px solid var(--border);background:#fafcfb}}
.gnode-phone{{border-color:#4a90d9;background:#eaf1fb}}.gnode-email{{border-color:#9b59b6;background:#f4ecf9}}.gnode-username{{border-color:var(--green);background:#e8f5e9}}.gnode-domain{{border-color:#e67e22;background:#fdf2e5}}.gnode-url{{border-color:#95a5a6;background:#f9f9f9}}
.identity-anchor{{text-align:center;padding:16px;margin-bottom:12px}}
.identity-anchor .name{{font-size:22px;font-weight:800;color:var(--accent2)}}
.identity-anchor .sub{{font-size:13px;color:var(--muted)}}
.tier-badge{{display:inline-block;padding:1px 6px;border-radius:5px;font-size:10px;font-weight:700;text-transform:uppercase;margin-left:4px}}
.tier-confirmed{{background:#d4edda;color:#155724;border:1px solid #c3e6cb}}
.tier-probable{{background:#fff3cd;color:#856404;border:1px solid #ffeaa7}}
.tier-unverified{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}}
.tier-rejected{{background:#eceff3;color:#4b5563;border:1px solid #cfd8e3}}
.tier-section{{margin:8px 0;padding:10px 14px;border-radius:8px}}
.tier-section h3{{margin:0 0 6px;font-size:13px}}
.tier-section-confirmed{{background:#e8f5e9;border-left:4px solid var(--green)}}
.tier-section-probable{{background:#fff8e1;border-left:4px solid var(--yellow)}}
.tier-section-unverified{{background:#fce4ec;border-left:4px solid var(--red)}}
.lane-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.lane-card{{border:1px solid var(--border);border-radius:12px;padding:14px;background:linear-gradient(180deg,#fff, #f8fbf9)}}
.lane-fast{{border-top:5px solid #228b5a}}
.lane-slow{{border-top:5px solid #8c5a2b}}
.lane-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
.lane-head h3{{margin:0;font-size:16px;color:var(--accent2)}}
.lane-snr{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.lane-snr-badge{{display:inline-block;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.25px}}
.lane-snr-confirmed{{background:#dff3e5;color:#1f6a35}}
.lane-snr-rejected{{background:#eceff3;color:#55606c}}
.lane-snr-dead{{background:#f6e6dc;color:#8b4f2a}}
.lane-metrics{{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;font-size:12px;color:var(--muted)}}
.lane-metrics span{{background:#eef3f0;border-radius:999px;padding:4px 8px}}
.lane-modules,.lane-highlights,.lane-errors{{margin-top:10px}}
.lane-highlights ul,.lane-errors ul{{margin:8px 0 0 18px;padding:0}}
.lane-evidence-block{{margin-top:8px;padding:10px 12px;border-radius:10px}}
.lane-evidence-confirmed{{background:#eef8f1;border-left:4px solid var(--green)}}
.lane-evidence-confirmed ul{{margin:8px 0 0 18px;padding:0}}
.lane-dead-ends{{margin-top:10px;border:1px dashed #c8d0d8;border-radius:10px;background:#f5f7f8}}
.lane-dead-ends summary{{padding:10px 12px;color:#5f6b76;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}}
.lane-muted-list{{margin:0;padding:0 12px 12px 30px;opacity:.6;font-size:12px}}
.lane-muted-list li{{margin:6px 0}}
.badge-lane-module{{background:#edf3f7;color:#23405e}}
@media(max-width:980px){{.hero-grid,.cards{{grid-template-columns:1fr}}.cards{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class='wrap'>

<div class='hero'>
  <div class='hero-grid'>
    <div>
            <h1>GONZO EVIDENCE PACK v3.0.2</h1>
            <p class='hero-sub'>Phase 8 Atomic Event-Driven Discovery: verification-first architecture with lane-aware deep recon, fast tactical signal, slow strategic depth, and explicit signal-to-noise control.</p>
    </div>
        <div class='hero-meta'>Generated: {esc(now)}<br>Engine: discovery_engine v3.0.2<br>Clusters: {len(self.clusters)}</div>
  </div>
  <div class='cards'>
    <div class='card'><div class='k'>Sources</div><div class='v'>{stats['total_metadata_files']}</div></div>
    <div class='card'><div class='k'>Confirmed</div><div class='v' style='color:#2a7d3f'>{stats['confirmed_observables']}</div></div>
    <div class='card'><div class='k'>Probable</div><div class='v' style='color:#b8860b'>{stats['probable_observables']}</div></div>
    <div class='card'><div class='k'>Unverified</div><div class='v' style='color:#b84c2e'>{stats['unverified_observables']}</div></div>
    <div class='card'><div class='k'>Rejected</div><div class='v'>{stats['rejected_targets']}</div></div>
    <div class='card'><div class='k'>Profiles</div><div class='v'>{stats['profile_urls']}</div></div>
    <div class='card'><div class='k'>Pivots</div><div class='v'>{stats['pending_pivots']}</div></div>
  </div>
</div>

<section class='section'><h2>{_E["summary"]} Executive Summary</h2><div class='pad exec'>
  {summary_html}
  <p style='margin-top:10px'><strong>Source coverage:</strong> {tool_badges}</p>
  <p class='hint'>v2 verification-first resolution across {stats['total_metadata_files']} tool outputs. {stats['rejected_targets']} target(s) filtered (hashes, placeholders, type mismatches).</p>
</div></section>

<section class='section'><h2>🏎️ Fast / Slow Lane Summary</h2><div class='pad'>
    <p class='hint'>Operational split of deep recon outputs into hot-path tactical findings and cold-path strategic expansion.</p>
    <p class='hint'>{lane_source_note or 'No deep recon artifact found in runs/. Lane summary falls back to dossier-linked observables only.'}</p>
    <p class='hint'>Legend: <span class='lane-snr-badge lane-snr-confirmed' title='Confirmed: corroborated or validated evidence ready for analyst attention.'>confirmed</span> <span class='lane-snr-badge lane-snr-rejected' title='Rejected: filtered false positives, such as platform artefacts or invalid profile hits.'>rejected</span> <span class='lane-snr-badge lane-snr-dead' title='Dead-end: leads that did not confirm and currently terminate without escalation.'>dead-end</span></p>
    <div class='lane-grid'>
        {lane_cards_html}
    </div>
</div></section>

<section class='section'><h2>{_E["anchor"]} Identity Anchor</h2><div class='pad'>
  {anchor_section}
  <div class='graph-grid'>
    {graph_nodes_html}
  </div>
</div></section>

<section class='section'><h2>{_E["link"]} Entity Link Graph</h2><div class='pad'>
  <p class='hint'>Links between observables — only applied when at least one side is confirmed/probable.</p>
  <table><tr><th>Observable A</th><th>Link Reason</th><th>Observable B</th><th>Confidence</th></tr>
  {graph_edges_html or "<tr><td colspan='4'>No links</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{_E["globe"]} Social Profiles ({len(primary.profile_urls) if primary else 0})</h2><div class='pad'>
  <p class='hint'>Profile URLs discovered by sherlock/maigret. Status: VERIFIED (HTTP 200 + content), SOFT (HTTP 200, low content), DEAD (4xx/5xx/timeout), UNCHECKED (not yet verified).</p>
  <table><tr><th>Platform</th><th>URL</th><th>Status</th></tr>
  {profile_rows_html or "<tr><td colspan='3'>No profiles found</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{_E["pivot"]} Auto-Pivot Queue ({len(pivot_queue)})</h2><div class='pad'>
  <p class='hint'>Observables needing further investigation. Reasons explain WHY each pivot is suggested.</p>
  <table><tr><th>Type</th><th>Value</th><th>Suggested Tools</th><th>Reason</th><th>Tier</th></tr>
  {pivot_rows_html or "<tr><td colspan='5'>No pending pivots</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{_E["chart"]} All Observables ({stats['total_observables']})</h2><div class='pad'>
  <table><tr><th>Type</th><th>Value</th><th>Source Tool</th><th>Target</th><th>Depth</th><th>Tier</th></tr>
  {obs_table_html}
  </table>
</div></section>

{secondary_section}

{rejected_section}

</div>
</body>
</html>"""

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(page, encoding="utf-8")

        return page
        '''


# ── CLI entry point ──────────────────────────────────────────────

def _cli():
    """
    HANNA Discovery Engine — CLI

    Usage:
      python3 discovery_engine.py --verify-all --db discovery.db
      python3 discovery_engine.py --ingest /path/to/exports/*.json --db discovery.db
      python3 discovery_engine.py --report --db discovery.db
      python3 discovery_engine.py --stats --db discovery.db
    """
    import argparse
    import glob

    parser = argparse.ArgumentParser(
        prog="discovery_engine",
        description="HANNA Discovery Engine v2 — verification-first orchestrator",
    )
    parser.add_argument("--db", metavar="PATH", help="SQLite database path (default: ~/Desktop/ОСІНТ_ВИВІД/runs/discovery.db)")
    parser.add_argument("--verify-all", action="store_true", help="Run HTTP verification for all unchecked profile URLs")
    parser.add_argument("--verify-content", action="store_true", help="Run content-match verification for soft_match URLs")
    parser.add_argument("--reverify-expired", action="store_true", help="Re-verify profiles whose TTL has expired")
    parser.add_argument("--ingest", nargs="*", metavar="JSON", help="Ingest metadata JSON exports")
    parser.add_argument("--report", metavar="OUT", nargs="?", const="auto", help="Generate HTML dossier report")
    parser.add_argument("--report-mode", choices=["internal", "shareable", "strict"], default="shareable", help="HTML dossier redaction level")
    parser.add_argument("--stats", action="store_true", help="Print observable and profile stats")
    parser.add_argument("--max-checks", type=int, default=200, metavar="N", help="Max URLs to verify (default: 200)")
    parser.add_argument("--timeout", type=float, default=5.0, metavar="SEC", help="Per-request timeout (default: 5)")

    args = parser.parse_args()

    # ── Resolve DB path ──
    db_path = args.db or str(DEFAULT_DB_PATH)
    if not Path(db_path).exists() and not args.ingest:
        print(f"DB not found: {db_path}")
        raise SystemExit(1)

    engine = DiscoveryEngine(db_path=db_path)

    did_something = False

    # ── Ingest ──
    if args.ingest:
        files = []
        for pattern in args.ingest:
            files.extend(glob.glob(pattern))
        if not files:
            print("No files matched ingest patterns.")
        else:
            for fpath in sorted(set(files)):
                print(f"  Ingesting: {fpath}")
                engine.ingest_metadata(fpath)
            engine.resolve_entities()
            print(f"  ✓ Ingested {len(files)} file(s), resolved entities.")
        did_something = True

    # ── Verify profiles ──
    if args.verify_all:
        before = engine.get_profile_stats()
        unchecked = before.get("unchecked", 0)
        if unchecked == 0:
            print("  No unchecked profile URLs to verify.")
        else:
            print(f"  Verifying {min(unchecked, args.max_checks)} profile URLs (timeout={args.timeout}s)...")
            engine.verify_profiles(max_checks=args.max_checks, timeout=args.timeout)
            after = engine.get_profile_stats()
            print(f"  ✓ Profile verification complete:")
            for status, count in sorted(after.items()):
                delta = count - before.get(status, 0)
                tag = f" (+{delta})" if delta > 0 else ""
                print(f"    {status:15s} {count:4d}{tag}")
        did_something = True

    # ── Content verification ──
    if args.verify_content:
        print(f"  Running content verification (max={args.max_checks}, timeout={args.timeout}s)...")
        counts = engine.verify_content(max_checks=args.max_checks, timeout=args.timeout)
        print(f"  ✓ Content verification: upgraded={counts.get('upgraded',0)}, "
              f"killed={counts.get('killed',0)}, unchanged={counts.get('unchanged',0)}, "
              f"errors={counts.get('errors',0)}, blacklisted={counts.get('skipped_blacklisted',0)}")
        did_something = True

    # ── TTL re-verification ──
    if args.reverify_expired:
        print(f"  Re-verifying expired TTL profiles (max={args.max_checks}, timeout={args.timeout}s)...")
        counts = engine.reverify_expired(max_checks=args.max_checks, timeout=args.timeout)
        print(f"  ✓ TTL re-verification: rechecked={counts['rechecked']}, "
              f"upgraded={counts['upgraded']}, downgraded={counts['downgraded']}, "
              f"unchanged={counts['unchanged']}")
        did_something = True

    # ── Stats ──
    if args.stats or not did_something:
        profile_stats = engine.get_profile_stats()
        obs_rows = engine.db.execute(
            "SELECT tier, COUNT(*) FROM observables GROUP BY tier"
        ).fetchall()
        link_count = engine.db.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]
        queue_count = engine.db.execute(
            "SELECT COUNT(*) FROM discovery_queue WHERE state='pending'"
        ).fetchone()[0]
        expired_count = engine.db.execute(
            "SELECT COUNT(*) FROM profile_urls WHERE valid_until IS NOT NULL AND valid_until < datetime('now')"
        ).fetchone()[0]

        print(f"\n{'='*50}")
        print(f"  HANNA Discovery Engine — DB Stats")
        print(f"  Database: {db_path}")
        print(f"{'='*50}")
        print(f"\n  Observables:")
        for row in obs_rows:
            print(f"    {row[0]:15s} {row[1]:4d}")
        print(f"\n  Profile URLs:")
        for status, count in sorted(profile_stats.items()):
            print(f"    {status:15s} {count:4d}")
        print(f"\n  Entity links:      {link_count}")
        print(f"  Pending pivots:    {queue_count}")
        print(f"  TTL expired URLs:  {expired_count}")
        did_something = True

    # ── Report ──
    if args.report:
        if args.report == "auto":
            out_path = str(RUNS_ROOT / "dossier.html")
        else:
            out_path = args.report
        engine.render_graph_report(output_path=out_path, redaction_mode=args.report_mode)
        print(f"\n📄 HTML report saved: {out_path}")


if __name__ == "__main__":
    _cli()
