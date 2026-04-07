"""ReconNGAdapter — run targeted recon-ng modules via scripted workspace."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import resolve_cli_timeout, run_cli


class ReconNGAdapter(ReconAdapter):
    """Execute recon-ng modules against domain/email/username targets."""

    name = "reconng"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        target_type, seed = self._detect_seed(target_name, known_usernames)
        if not seed:
            return []
        return self._run_reconng(seed, target_type)

    def _detect_seed(self, target_name: str, known_usernames: list[str]) -> tuple[str, str]:
        for value in known_usernames:
            value = value.strip()
            if "@" in value:
                return "email", value
        for value in [target_name] + known_usernames:
            value = value.strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                value = value.split("://", 1)[1].split("/", 1)[0]
            if "." in value and " " not in value:
                return "domain", value
        for value in known_usernames:
            if value.strip():
                return "username", value.strip()
        return "", ""

    def _run_reconng(self, seed: str, target_type: str) -> list[ReconHit]:
        reconng_bin = os.environ.get("RECONNG_BIN", "")
        repo_root = Path(__file__).resolve().parents[2] / "tools" / "recon-ng"
        repo_bin = repo_root / "recon-ng"
        venv_python = repo_root / ".venv" / "bin" / "python"
        with tempfile.TemporaryDirectory(prefix="hanna-reconng-") as tmpdir:
            workspace = "hanna_auto"
            db_path = Path.home() / ".recon-ng" / "workspaces" / workspace / "data.db"
            lines = [f"workspaces create {workspace}"]
            if target_type == "domain":
                lines += [
                    f"db insert domains domain={seed}",
                    "modules load recon/domains-hosts/bing_domain_web",
                    "run",
                    "modules load recon/domains-contacts/hunter_io",
                    "run",
                ]
            elif target_type == "email":
                lines += [
                    f"db insert contacts email={seed}",
                    "modules load recon/contacts-credentials/hibp_paste",
                    "run",
                ]
            else:
                lines += [
                    f"db insert profiles username={seed}",
                    "modules load recon/profiles-profiles/namechk",
                    "run",
                ]
            lines.append("exit")
            rc_path = Path(tmpdir) / "script.rc"
            rc_path.write_text("\n".join(lines), encoding="utf-8")
            cmd = [reconng_bin] if reconng_bin else []
            if venv_python.exists() and repo_bin.exists() and not cmd:
                cmd = [str(venv_python), str(repo_bin)]
            elif repo_bin.exists() and not cmd:
                cmd = [str(repo_bin)]
            elif not cmd:
                cmd = ["recon-ng"]
            proc = run_cli(
                cmd + ["--no-analytics", "--no-marketplace", "-r", str(rc_path)],
                timeout=resolve_cli_timeout(self.name, self.timeout, 20),
            )
            if not proc:
                return []
            return self._read_workspace_db(db_path, seed)

    def _read_workspace_db(self, db_path: Path, seed: str) -> list[ReconHit]:
        if not db_path.exists():
            return []
        hits: list[ReconHit] = []
        try:
            db = sqlite3.connect(db_path)
        except sqlite3.Error:
            return hits
        try:
            for table, obs_type, field in [
                ("hosts", "infrastructure", "host"),
                ("contacts", "email", "email"),
                ("profiles", "url", "url"),
            ]:
                try:
                    rows = db.execute(f"SELECT * FROM {table} LIMIT 20").fetchall()
                except sqlite3.Error:
                    continue
                cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})").fetchall()]
                for row in rows:
                    record = dict(zip(cols, row))
                    value = record.get(field) or record.get("username") or record.get("email") or record.get("host")
                    if not value:
                        continue
                    hits.append(ReconHit(
                        observable_type=obs_type,
                        value=str(value),
                        source_module=self.name,
                        source_detail=f"reconng:{table}",
                        confidence=0.5,
                        raw_record=record,
                        timestamp=datetime.now().isoformat(),
                        cross_refs=[seed],
                    ))
        finally:
            db.close()
        return hits
