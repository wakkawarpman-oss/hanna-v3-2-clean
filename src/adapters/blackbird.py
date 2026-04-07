"""BlackbirdAdapter — username to platform profile discovery."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class BlackbirdAdapter(ReconAdapter):
    """Find usernames across modern platforms using Blackbird."""

    name = "blackbird"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for username in known_usernames[:10]:
            hits.extend(self._run_blackbird(username.strip()))
        return hits

    def _run_blackbird(self, username: str) -> list[ReconHit]:
        if not username or "@" in username or "/" in username:
            return []
        blackbird_bin = os.environ.get("BLACKBIRD_BIN", "")
        repo_root = Path(__file__).resolve().parents[2] / "tools" / "blackbird"
        repo_script = repo_root / "blackbird.py"
        venv_python = repo_root / ".venv" / "bin" / "python"
        cmd = [blackbird_bin] if blackbird_bin else []
        if venv_python.exists() and repo_script.exists() and not cmd:
            cmd = [str(venv_python), str(repo_script)]
        elif repo_script.exists() and not cmd:
            cmd = ["python3", str(repo_script)]
        elif not cmd:
            cmd = ["blackbird"]
        proc = run_cli(
            cmd + ["-u", username, "--json", "--no-update"],
            timeout=self.timeout * 8,
        )
        if not proc:
            return []

        output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if not output:
            return []

        hits: list[ReconHit] = []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return hits

        profiles = data if isinstance(data, list) else data.get("results", data.get("sites", []))
        for item in profiles:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            site = item.get("site") or item.get("name") or "unknown"
            if not url:
                continue
            hits.append(ReconHit(
                observable_type="url",
                value=url,
                source_module=self.name,
                source_detail=f"blackbird:{site}",
                confidence=0.55,
                raw_record=item,
                timestamp=datetime.now().isoformat(),
                cross_refs=[username],
            ))
        return hits[:100]
