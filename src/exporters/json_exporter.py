from __future__ import annotations

import json
import re
from pathlib import Path

from models import RunResult


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unknown"


def _timestamp_fragment(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14] or "00000000000000"


def export_run_result_json(result: RunResult, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_slugify(result.target_name)}-{result.mode}-{_timestamp_fragment(result.finished_at or result.started_at)}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path