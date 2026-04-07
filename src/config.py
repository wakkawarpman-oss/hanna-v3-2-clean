"""
config.py — Centralized configuration for HANNA OSINT pipeline.

Single source of truth for paths, magic numbers, and runtime settings.
All modules import from here instead of hardcoding values.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default

# ── Load .env if present ─────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv optional

# ── Filesystem layout ────────────────────────────────────────────

RUNS_ROOT = Path(os.environ.get(
    "HANNA_RUNS_ROOT",
    str(Path.home() / "Desktop" / "ОСІНТ_ВИВІД" / "runs"),
))

EXPORTS_DIR = RUNS_ROOT / "exports"
LOGS_DIR = RUNS_ROOT / "logs"
HTML_DIR = EXPORTS_DIR / "html" / "dossiers"
PROFILES_DIR = RUNS_ROOT.parent / "profiles"
DEFAULT_DB_PATH = RUNS_ROOT / "discovery.db"

# ── Adapter limits ───────────────────────────────────────────────

MAX_JSONL_LINES = 500_000          # max lines per leak file scan
MAX_BODY_BYTES = 512_000           # max bytes to read per URL for content verification
MAX_PROFILE_URLS = 50              # max profile URLs rendered per cluster
MAX_DISCOVERY_DEPTH = 3            # max recursive pivot depth
ADAPTER_REQ_CAP = 15               # max per-request timeout inside adapters (seconds)
WORKER_TIMEOUT = 120               # default hard timeout per adapter (seconds)
VERIFY_WORKERS = int(os.environ.get("HANNA_VERIFY_WORKERS", "10"))
CLI_TIMEOUT_SAFETY_MARGIN = _env_int("HANNA_CLI_TIMEOUT_SAFETY_MARGIN", 5)

# ── Priority timeouts ───────────────────────────────────────────

PRIORITY_WORKER_TIMEOUT = {
    0: 300,
    1: 120,
    2: 120,
    3: 120,
}

# Module-specific worker overrides for long-running CLI tools.
MODULE_WORKER_TIMEOUT_DEFAULTS = {
    "nuclei": 180,
    "amass": 180,
    "social_analyzer": 180,
    "metagoofil": 240,
    "reconng": 240,
    "eyewitness": 300,
}
MODULE_WORKER_TIMEOUT = {
    name: _env_int(f"HANNA_TIMEOUT_{name.upper()}_WORKER", default)
    for name, default in MODULE_WORKER_TIMEOUT_DEFAULTS.items()
}

# Nuclei operational tuning.
NUCLEI_PROFILE = os.environ.get("HANNA_NUCLEI_PROFILE", "quick").strip().lower() or "quick"
NUCLEI_QUICK_TARGET_CAP = _env_int("HANNA_NUCLEI_QUICK_TARGET_CAP", 2)
NUCLEI_DEEP_TARGET_CAP = _env_int("HANNA_NUCLEI_DEEP_TARGET_CAP", 5)
NUCLEI_QUICK_RATE_LIMIT = _env_int("HANNA_NUCLEI_QUICK_RATE_LIMIT", 20)
NUCLEI_DEEP_RATE_LIMIT = _env_int("HANNA_NUCLEI_DEEP_RATE_LIMIT", 50)
NUCLEI_QUICK_BULK_SIZE = _env_int("HANNA_NUCLEI_QUICK_BULK_SIZE", 5)
NUCLEI_DEEP_BULK_SIZE = _env_int("HANNA_NUCLEI_DEEP_BULK_SIZE", 10)
NUCLEI_QUICK_CONCURRENCY = _env_int("HANNA_NUCLEI_QUICK_CONCURRENCY", 3)
NUCLEI_DEEP_CONCURRENCY = _env_int("HANNA_NUCLEI_DEEP_CONCURRENCY", 5)
NUCLEI_QUICK_TIMEOUT_MULTIPLIER = _env_float("HANNA_NUCLEI_QUICK_TIMEOUT_MULTIPLIER", 6.0)
NUCLEI_DEEP_TIMEOUT_MULTIPLIER = _env_float("HANNA_NUCLEI_DEEP_TIMEOUT_MULTIPLIER", 10.0)

# ── Retry policy ─────────────────────────────────────────────────

RETRY_MAX_ATTEMPTS = int(os.environ.get("HANNA_RETRY_MAX", "3"))
RETRY_BASE_DELAY = float(os.environ.get("HANNA_RETRY_DELAY", "1.0"))
RETRY_MAX_DELAY = 10.0

# ── Health tracking ──────────────────────────────────────────────

ADAPTER_FAILURE_THRESHOLD = 3      # consecutive failures before auto-skip

# ── OPSEC ────────────────────────────────────────────────────────

REQUIRE_PROXY = os.environ.get("HANNA_REQUIRE_PROXY", "0") == "1"
LOG_ENCRYPT = os.environ.get("HANNA_LOG_ENCRYPT", "0") == "1"
LOG_ENCRYPT_KEY = os.environ.get("HANNA_LOG_KEY", "")

# ── Confidence ───────────────────────────────────────────────────

CROSS_CONFIRM_BOOST = 0.2          # boost for multi-source corroboration
ENTROPY_THRESHOLD = 3.8            # Shannon entropy above this → likely a token, not username

# ── SQLite ───────────────────────────────────────────────────────

SCHEMA_VERSION = 2                 # current schema version (PRAGMA user_version)
