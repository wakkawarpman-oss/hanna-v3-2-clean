from __future__ import annotations

import json
import os
from pathlib import Path


_REQUIRED_METADATA_KEYS = frozenset({"target", "profile", "status"})
_GENERATED_FILENAME_SUFFIXES = (
    ".metadata.json",
    ".stix.json",
)
_GENERATED_FILENAMES = {
    "manifest.json",
    "inventory.json",
    "reset-result.json",
}
_GENERATED_PAYLOAD_KEYS = frozenset({
    "runtime_summary",
    "outcomes",
    "all_hits",
    "artifacts",
    "checks",
    "presets",
    "modules",
    "removed",
    "missing",
})


def _is_candidate_filename(path: Path) -> bool:
    name = path.name
    if name in _GENERATED_FILENAMES:
        return False
    return not any(name.endswith(suffix) for suffix in _GENERATED_FILENAME_SUFFIXES)


def _iter_json_candidate_paths(root: Path) -> list[Path]:
    try:
        with os.scandir(root) as entries:
            candidates = [
                Path(entry.path)
                for entry in entries
                if entry.is_file() and entry.name.lower().endswith(".json") and _is_candidate_filename(Path(entry.name))
            ]
    except FileNotFoundError:
        return []
    return sorted(candidates)


def is_ingest_metadata_file(path: str | Path) -> bool:
    candidate = Path(path)
    if not candidate.is_file() or candidate.suffix.lower() != ".json":
        return False
    if not _is_candidate_filename(candidate):
        return False

    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(payload, dict):
        return False

    keys = set(payload.keys())
    if _REQUIRED_METADATA_KEYS.issubset(keys):
        return True
    if _GENERATED_PAYLOAD_KEYS & keys:
        return False
    return False


def discover_ingest_metadata_paths(exports_dir: str | Path) -> list[Path]:
    root = Path(exports_dir)
    return [path for path in _iter_json_candidate_paths(root) if is_ingest_metadata_file(path)]