"""SubfinderAdapter — passive subdomain discovery via ProjectDiscovery subfinder."""
from __future__ import annotations

import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class SubfinderAdapter(ReconAdapter):
    """Enumerate passive subdomains for a root domain."""

    name = "subfinder"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for domain in self._collect_domains(target_name, known_usernames)[:5]:
            hits.extend(self._run_subfinder(domain))
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

    def _run_subfinder(self, domain: str) -> list[ReconHit]:
        subfinder_bin = os.environ.get("SUBFINDER_BIN", "subfinder")
        proc = run_cli([subfinder_bin, "-d", domain, "-silent"], timeout=self.timeout * 6)
        if not proc or not proc.stdout.strip():
            return []
        hits: list[ReconHit] = []
        for sub in proc.stdout.splitlines():
            sub = sub.strip().lower()
            if not sub:
                continue
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=sub,
                source_module=self.name,
                source_detail=f"subfinder:{domain}",
                confidence=0.55,
                raw_record={"domain": domain, "subdomain": sub},
                timestamp=datetime.now().isoformat(),
                cross_refs=[domain],
            ))
        return hits
