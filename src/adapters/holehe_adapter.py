"""HoleheAdapter — email service-account discovery via holehe."""
from __future__ import annotations

import os
import re
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class HoleheAdapter(ReconAdapter):
    """Map an email address to services where it appears registered."""

    name = "holehe"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        emails = [u.strip().lower() for u in known_usernames if "@" in u]
        for email in list(dict.fromkeys(emails))[:5]:
            hits.extend(self._run_holehe(email))
        return hits

    def _run_holehe(self, email: str) -> list[ReconHit]:
        holehe_bin = os.environ.get("HOLEHE_BIN", "holehe")
        proc = run_cli(
            [holehe_bin, email, "--only-used", "--no-color"],
            timeout=self.timeout * 10,
        )
        if not proc:
            return []

        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        hits: list[ReconHit] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = re.search(r"\[(?:\+|x)\]\s*([^:]+)(?::\s*(.*))?", stripped)
            if not match or stripped.startswith("[x]"):
                continue
            service = match.group(1).strip()
            detail = (match.group(2) or "registered").strip()
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=f"{email} @ {service}",
                source_module=self.name,
                source_detail=f"holehe:{service}",
                confidence=0.6,
                raw_record={"email": email, "service": service, "detail": detail},
                timestamp=datetime.now().isoformat(),
                cross_refs=[email],
            ))
        return hits
