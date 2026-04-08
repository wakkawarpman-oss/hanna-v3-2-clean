from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from exporters.json_exporter import export_run_result_json
from exporters.stix_exporter import export_run_result_stix
from models import RunResult


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unknown"


def _timestamp_fragment(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14] or "00000000000000"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _append_file(zf: zipfile.ZipFile, manifest: dict[str, object], path: Path, arcname: str) -> None:
    zf.write(path, arcname=arcname)
    manifest["artifacts"].append({"name": arcname, "sha256": _sha256(path)})


def _collect_supporting_paths(result: RunResult) -> list[tuple[Path, str]]:
    collected: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    for outcome in result.outcomes:
        if not outcome.log_path:
            continue
        path = Path(outcome.log_path)
        if path.exists() and path not in seen:
            collected.append((path, f"logs/{path.name}"))
            seen.add(path)

    extra_artifacts = result.extra.get("artifacts") if isinstance(result.extra, dict) else None
    artifact_candidates: list[str] = []
    if isinstance(extra_artifacts, dict):
        artifact_candidates.extend(str(value) for value in extra_artifacts.values())
    elif isinstance(extra_artifacts, list):
        artifact_candidates.extend(str(value) for value in extra_artifacts)

    for raw_path in artifact_candidates:
        path = Path(raw_path)
        if path.exists() and path not in seen:
            collected.append((path, f"artifacts/{path.name}"))
            seen.add(path)

    return collected


def export_run_result_zip(
    result: RunResult,
    output_dir: str | Path,
    html_path: str | Path | None = None,
    report_mode: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = export_run_result_json(result, output_dir)
    stix_path = export_run_result_stix(result, output_dir)
    html_file = Path(html_path) if html_path else None
    if report_mode and (html_file is None or not html_file.exists()):
        raise FileNotFoundError("ZIP export with report_mode requires a rendered HTML dossier")

    zip_path = output_dir / f"{_slugify(result.target_name)}-{result.mode}-{_timestamp_fragment(result.finished_at or result.started_at)}.zip"
    manifest: dict[str, object] = {
        "target_name": result.target_name,
        "mode": result.mode,
        "report_mode": report_mode,
        "artifacts": [],
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in [json_path, stix_path]:
            _append_file(zf, manifest, path, path.name)

        if html_file and html_file.exists():
            _append_file(zf, manifest, html_file, html_file.name)

        for path, arcname in _collect_supporting_paths(result):
            _append_file(zf, manifest, path, arcname)

        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)

    return zip_path