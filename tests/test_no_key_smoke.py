from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_no_key_smoke_completes_within_sixty_seconds():
    repo_root = Path(__file__).resolve().parent.parent
    out_root = repo_root / ".cache" / "no-key-smoke"

    completed = subprocess.run(
        ["./scripts/test_no_keys.sh", "example.com"],
        cwd=repo_root,
        timeout=60,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout

    metadata_path = out_root / "no-key-smoke.metadata.json"
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["runtime_summary"]["queued"] == 4
    assert payload["runtime_summary"]["worker_crash"] == 0