"""MetagoofilAdapter — extract metadata from public documents."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import resolve_cli_timeout, run_cli


class MetagoofilAdapter(ReconAdapter):
    """Collect emails and usernames leaked via public document metadata."""

    name = "metagoofil"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for domain in self._collect_domains(target_name, known_usernames)[:3]:
            hits.extend(self._run_metagoofil(domain))
        return hits

    def _collect_domains(self, target_name: str, known_usernames: list[str]) -> list[str]:
        domains: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip().lower()
            if not value or "@" in value or " " in value:
                continue
            if value.startswith(("http://", "https://")):
                value = value.split("://", 1)[1].split("/", 1)[0]
            if "." in value:
                domains.append(value)
        return list(dict.fromkeys(domains))

    def _run_metagoofil(self, domain: str) -> list[ReconHit]:
        meta_bin = os.environ.get("METAGOOFIL_BIN", "")
        repo_root = Path(__file__).resolve().parents[2] / "tools" / "metagoofil"
        repo_script = repo_root / "metagoofil.py"
        venv_python = repo_root / ".venv" / "bin" / "python"
        with tempfile.TemporaryDirectory(prefix="hanna-metagoofil-") as tmpdir:
            cmd = [meta_bin] if meta_bin else []
            if venv_python.exists() and repo_script.exists() and not cmd:
                cmd = [str(venv_python), str(repo_script)]
            elif repo_script.exists() and not cmd:
                cmd = ["python3", str(repo_script)]
            elif not cmd:
                cmd = ["metagoofil"]
            proc = run_cli(
                cmd + [
                    "-d", domain,
                    "-t", "pdf,docx,xlsx,pptx",
                    "-l", "20",
                    "-n", "10",
                    "-o", tmpdir,
                    "-f", os.path.join(tmpdir, "report.html"),
                    "-e", "5",
                ],
                timeout=resolve_cli_timeout(self.name, self.timeout, 15),
            )
            if not proc:
                return []
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        hits: list[ReconHit] = []
        for email in sorted(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", output))):
            hits.append(ReconHit(
                observable_type="email",
                value=email.lower(),
                source_module=self.name,
                source_detail=f"metagoofil:email:{domain}",
                confidence=0.58,
                raw_record={"domain": domain, "email": email},
                timestamp=datetime.now().isoformat(),
                cross_refs=[domain],
            ))

        for username in sorted(set(re.findall(r"[Uu]ser(?:name)?\s*[:=]\s*([A-Za-z0-9_.-]{3,40})", output))):
            hits.append(ReconHit(
                observable_type="username",
                value=username,
                source_module=self.name,
                source_detail=f"metagoofil:username:{domain}",
                confidence=0.45,
                raw_record={"domain": domain, "username": username},
                timestamp=datetime.now().isoformat(),
                cross_refs=[domain],
            ))
        return hits
