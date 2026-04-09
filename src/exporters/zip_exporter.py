from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
import re
import zipfile
from pathlib import Path

from config import RUNS_ROOT
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


_ARTIFACT_KEY_RE = re.compile(r"(?:artifact|report|screenshot|capture|media|output|export|file)$", re.IGNORECASE)


def _iter_path_strings(value: object, *, parent_key: str | None = None) -> Iterable[str]:
    if isinstance(value, (str, Path)):
        if parent_key and _ARTIFACT_KEY_RE.search(parent_key):
            yield str(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_name = str(key)
            if isinstance(item, dict):
                yield from _iter_path_strings(item, parent_key=key_name)
                continue
            if isinstance(item, (list, tuple, set)):
                if _ARTIFACT_KEY_RE.search(key_name):
                    yield from _iter_path_strings(item, parent_key=key_name)
                continue
            if _ARTIFACT_KEY_RE.search(key_name):
                yield from _iter_path_strings(item, parent_key=key_name)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_path_strings(item, parent_key=parent_key)


def _collect_tree(path: Path, prefix: str) -> list[tuple[Path, str]]:
    if path.is_file():
        return [(path, f"{prefix}/{path.name}")]

    collected: list[tuple[Path, str]] = []
    try:
        for child in sorted(path.rglob("*")):
            if child.is_file():
                collected.append((child, f"{prefix}/{path.name}/{child.relative_to(path).as_posix()}"))
    except OSError:
        return []
    return collected


def _is_allowed_artifact_path(path: Path, allowed_roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in allowed_roots)


def _approved_artifact_roots(
    output_dir: Path,
    html_file: Path | None,
) -> tuple[Path, ...]:
    roots = {output_dir.resolve(), RUNS_ROOT.resolve()}
    if html_file:
        roots.add(html_file.resolve().parent)
    return tuple(sorted(roots))


def _collect_supporting_paths(result: RunResult, allowed_roots: tuple[Path, ...]) -> list[tuple[Path, str]]:
    collected: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def _remember(path: Path, prefix: str) -> None:
        if not _is_allowed_artifact_path(path, allowed_roots):
            return
        for file_path, arcname in _collect_tree(path, prefix):
            resolved = file_path.resolve()
            if resolved in seen:
                continue
            collected.append((file_path, arcname))
            seen.add(resolved)

    for outcome in result.outcomes:
        if not outcome.log_path:
            continue
        path = Path(outcome.log_path)
        if path.exists():
            _remember(path, "logs")

    extra_artifacts = result.extra.get("artifacts") if isinstance(result.extra, dict) else None
    artifact_candidates: list[str] = []
    if isinstance(extra_artifacts, dict):
        artifact_candidates.extend(str(value) for value in extra_artifacts.values())
    elif isinstance(extra_artifacts, list):
        artifact_candidates.extend(str(value) for value in extra_artifacts)

    for raw_path in artifact_candidates:
        path = Path(raw_path)
        if path.exists():
            _remember(path, "artifacts")

    hit_candidates = list(result.all_hits)
    if not hit_candidates:
        for outcome in result.outcomes:
            hit_candidates.extend(outcome.hits)

    for hit in hit_candidates:
        for raw_path in _iter_path_strings(hit.raw_record):
            path = Path(raw_path)
            if path.exists():
                _remember(path, "artifacts")
        for raw_path in hit.cross_refs:
            path = Path(raw_path)
            if path.exists():
                _remember(path, "artifacts")

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
    allowed_roots = _approved_artifact_roots(output_dir, html_file)

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

        for path, arcname in _collect_supporting_paths(result, allowed_roots):
            _append_file(zf, manifest, path, arcname)

        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)

    return zip_path