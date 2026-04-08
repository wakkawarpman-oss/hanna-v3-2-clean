"""Tests for config.py — centralized configuration."""
from __future__ import annotations

from pathlib import Path

from config import (
    ADAPTER_FAILURE_THRESHOLD,
    ADAPTER_REQ_CAP,
    CLI_TIMEOUT_SAFETY_MARGIN,
    DEFAULT_DB_PATH,
    MAX_BODY_BYTES,
    MAX_JSONL_LINES,
    MODULE_WORKER_TIMEOUT,
    NUCLEI_DEEP_TARGET_CAP,
    NUCLEI_PROFILE,
    NUCLEI_QUICK_TARGET_CAP,
    PRIORITY_WORKER_TIMEOUT,
    RETRY_MAX_ATTEMPTS,
    RUNS_ROOT,
    SCHEMA_VERSION,
    VERIFY_WORKERS,
    WORKER_TIMEOUT,
)


class TestConfigDefaults:
    def test_runs_root_is_path(self):
        assert isinstance(RUNS_ROOT, Path)

    def test_db_path_under_runs(self):
        assert str(DEFAULT_DB_PATH).startswith(str(RUNS_ROOT))

    def test_limits_positive(self):
        assert MAX_JSONL_LINES > 0
        assert MAX_BODY_BYTES > 0
        assert ADAPTER_REQ_CAP > 0
        assert WORKER_TIMEOUT > 0
        assert VERIFY_WORKERS > 0

    def test_retry_sane(self):
        assert 1 <= RETRY_MAX_ATTEMPTS <= 10

    def test_cli_timeout_margin_sane(self):
        assert 1 <= CLI_TIMEOUT_SAFETY_MARGIN <= 30

    def test_adapter_threshold_sane(self):
        assert 1 <= ADAPTER_FAILURE_THRESHOLD <= 20

    def test_schema_version(self):
        assert SCHEMA_VERSION >= 1

    def test_module_worker_timeouts_cover_long_tools(self):
        assert PRIORITY_WORKER_TIMEOUT[0] == 300
        assert 15 <= PRIORITY_WORKER_TIMEOUT[1] <= 60
        assert 15 <= PRIORITY_WORKER_TIMEOUT[2] <= 60
        assert 15 <= PRIORITY_WORKER_TIMEOUT[3] <= 60
        assert MODULE_WORKER_TIMEOUT["nuclei"] <= 60
        assert MODULE_WORKER_TIMEOUT["eyewitness"] <= 60

    def test_nuclei_profile_config_sane(self):
        assert NUCLEI_PROFILE in {"quick", "deep"}
        assert NUCLEI_DEEP_TARGET_CAP >= NUCLEI_QUICK_TARGET_CAP >= 1
