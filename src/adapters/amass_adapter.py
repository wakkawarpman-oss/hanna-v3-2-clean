"""AmassAdapter — passive asset enumeration via OWASP Amass."""
from __future__ import annotations

import os
import re
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class AmassAdapter(ReconAdapter):
    """Enumerate subdomains and ASN-linked assets."""

    name = "amass"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for domain in self._collect_domains(target_name, known_usernames)[:3]:
            hits.extend(self._run_amass(domain))
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

    def _run_amass(self, domain: str) -> list[ReconHit]:
        amass_bin = os.environ.get("AMASS_BIN", "amass")
        proc = run_cli([amass_bin, "enum", "-passive", "-d", domain], timeout=self.timeout * 12)
        if not proc or not proc.stdout.strip():
            return []
        hits: list[ReconHit] = []
        for line in proc.stdout.splitlines():
            value = line.strip()
            if not value:
                continue
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=value,
                    source_module=self.name,
                    source_detail=f"amass:ip:{domain}",
                    confidence=0.5,
                    raw_record={"domain": domain, "ip": value},
                    timestamp=datetime.now().isoformat(),
                    cross_refs=[domain],
                ))
            elif "." in value:
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=value.lower(),
                    source_module=self.name,
                    source_detail=f"amass:subdomain:{domain}",
                    confidence=0.58,
                    raw_record={"domain": domain, "subdomain": value},
                    timestamp=datetime.now().isoformat(),
                    cross_refs=[domain],
                ))
        return hits
