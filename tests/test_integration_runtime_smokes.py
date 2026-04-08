from __future__ import annotations

import json
import zipfile

import cli as cli_mod
from runners.aggregate import AggregateRunner
from runners.manual import ManualRunner
from registry import MODULES

from adapters.base import DependencyUnavailableError


def test_manual_runtime_smoke_exports_artifacts(tmp_path):
    runner = ManualRunner()
    result = runner.run(
        module_name="ua_phone",
        target_name="Phone pivot",
        known_phones=["+380991234567"],
    )

    export_dir = tmp_path / "artifacts"
    exported = cli_mod._export_result_artifacts(
        result=result,
        export_formats=["json", "stix", "zip"],
        export_dir=str(export_dir),
    )

    assert result.mode == "manual"
    assert result.runtime_summary()["queued"] == 1
    assert result.runtime_summary()["completed"] == 1
    assert set(result.runtime_summary()["exports"]) == {"json", "stix", "zip"}
    assert all((export_dir / path.split("/")[-1]).exists() for path in exported.values())
    with zipfile.ZipFile(exported["zip"]) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert any(name.endswith(".json") for name in names)


def test_aggregate_runtime_smoke_tracks_missing_credentials(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)

    runner = AggregateRunner(max_workers=1)
    result = runner.run(
        target_name="Case",
        known_phones=["+380991234567"],
        modules=["ua_phone", "firms"],
    )

    summary = result.runtime_summary()
    assert result.mode == "aggregate"
    assert summary["queued"] == 2
    assert summary["completed"] == 1
    assert summary["skipped_missing_credentials"] == 1
    assert summary["timed_out"] == 0
    assert any(err.get("error_kind") == "missing_credentials" for err in result.errors)


def test_runtime_summary_block_renders_compact_json(capsys):
    class StubResult:
        def runtime_summary(self):
            return {
                "target_name": "Case",
                "mode": "chain",
                "queued": 2,
                "completed": 1,
                "failed": 0,
                "timed_out": 0,
                "skipped_missing_credentials": 1,
                "exports": ["json"],
                "report_mode": "shareable",
            }

    cli_mod._print_runtime_summary_block(StubResult())

    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == "Runtime summary JSON:"
    payload = json.loads(out[1])
    assert payload["mode"] == "chain"
    assert payload["skipped_missing_credentials"] == 1


def test_manual_runtime_smoke_tracks_missing_binary(monkeypatch):
    monkeypatch.setenv("NUCLEI_BIN", "/definitely/missing/nuclei")

    runner = ManualRunner()
    result = runner.run(
        module_name="nuclei",
        target_name="https://example.com",
    )

    summary = result.runtime_summary()
    assert summary["missing_binary"] == 1
    assert any(err.get("error_kind") == "missing_binary" for err in result.errors)


def test_manual_runtime_tracks_dependency_unavailable(monkeypatch):
    class BrokenAdapter:
        region = "global"

        def __init__(self, proxy=None, timeout=0.0, leak_dir=None):
            pass

        def search(self, target_name, known_phones, known_usernames):
            raise DependencyUnavailableError("broken shared library")

    monkeypatch.setitem(MODULES, "broken_dep", BrokenAdapter)

    runner = ManualRunner()
    result = runner.run(module_name="broken_dep", target_name="Case")

    summary = result.runtime_summary()
    assert summary["dependency_unavailable"] == 1
    assert any(err.get("error_kind") == "dependency_unavailable" for err in result.errors)