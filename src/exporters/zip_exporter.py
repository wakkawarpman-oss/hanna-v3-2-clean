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


def export_run_result_zip(result: RunResult, output_dir: str | Path, html_path: str | Path | None = None) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = export_run_result_json(result, output_dir)
    stix_path = export_run_result_stix(result, output_dir)
    html_file = Path(html_path) if html_path else None

    zip_path = output_dir / f"{_slugify(result.target_name)}-{result.mode}-{_timestamp_fragment(result.finished_at or result.started_at)}.zip"
    manifest: dict[str, object] = {
        "target_name": result.target_name,
        "mode": result.mode,
        "artifacts": [],
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in [json_path, stix_path]:
            zf.write(path, arcname=path.name)
            manifest["artifacts"].append({"name": path.name, "sha256": _sha256(path)})

        if html_file and html_file.exists():
            zf.write(html_file, arcname=html_file.name)
            manifest["artifacts"].append({"name": html_file.name, "sha256": _sha256(html_file)})

        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)

    return zip_path