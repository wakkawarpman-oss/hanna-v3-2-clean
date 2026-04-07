from __future__ import annotations

import json
import zipfile
from pathlib import Path

from adapters.base import ReconHit
from exporters.json_exporter import export_run_result_json
from exporters.stix_exporter import build_stix_bundle, export_run_result_stix
from exporters.zip_exporter import export_run_result_zip
from models import AdapterOutcome, RunResult


def _sample_result() -> RunResult:
    hit = ReconHit(
        observable_type="email",
        value="user@example.com",
        source_module="ghunt",
        source_detail="fixture",
        confidence=0.8,
        raw_record={"source": "fixture"},
    )
    return RunResult(
        target_name="Test Target",
        mode="aggregate",
        modules_run=["ghunt"],
        outcomes=[AdapterOutcome(module_name="ghunt", lane="fast", hits=[hit], elapsed_sec=0.1)],
        all_hits=[hit],
        cross_confirmed=[hit],
        new_emails=[hit.value],
        started_at="2026-04-08T10:00:00",
        finished_at="2026-04-08T10:00:01",
        extra={"output_path": "report.html"},
    )


def test_json_exporter_writes_run_result_payload(tmp_path):
    path = export_run_result_json(_sample_result(), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.exists()
    assert payload["schema_version"] == 1
    assert payload["target_name"] == "Test Target"
    assert payload["all_hits"][0]["value"] == "user@example.com"


def test_stix_exporter_writes_bundle_with_identity_and_observed_data(tmp_path):
    result = _sample_result()
    bundle = build_stix_bundle(result)
    path = export_run_result_stix(result, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    object_types = {obj["type"] for obj in bundle["objects"]}
    assert bundle["type"] == "bundle"
    assert "identity" in object_types
    assert "observed-data" in object_types
    assert payload["type"] == "bundle"


def test_zip_exporter_packages_manifest_and_artifacts(tmp_path):
    result = _sample_result()
    html_path = tmp_path / "dossier.html"
    html_path.write_text("<html>safe</html>", encoding="utf-8")

    path = export_run_result_zip(result, tmp_path, html_path=html_path, report_mode="shareable")

    assert path.exists()
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert any(name.endswith(".json") for name in names)
        assert any(name.endswith(".stix.json") for name in names)
        assert "dossier.html" in names

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["target_name"] == "Test Target"
        assert manifest["report_mode"] == "shareable"
        assert len(manifest["artifacts"]) >= 3


def test_zip_exporter_requires_html_when_report_mode_is_declared(tmp_path):
    result = _sample_result()

    try:
        export_run_result_zip(result, tmp_path, report_mode="strict")
    except FileNotFoundError as exc:
        assert "requires a rendered HTML dossier" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError when report_mode is set without HTML dossier")