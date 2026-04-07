"""ShodanAdapter — internet-exposed host enrichment via shodan CLI."""
from __future__ import annotations

import json
import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class ShodanAdapter(ReconAdapter):
    """Query Shodan for internet-facing service banners and vulnerabilities."""

    name = "shodan"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for target in self._collect_targets(target_name, known_usernames)[:5]:
            hits.extend(self._run_shodan(target))
        return hits

    def _collect_targets(self, target_name: str, known_usernames: list[str]) -> list[str]:
        targets: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip()
            if not value or "@" in value or " " in value:
                continue
            if value.startswith(("http://", "https://")):
                value = value.split("://", 1)[1].split("/", 1)[0]
            targets.append(value)
        return list(dict.fromkeys(targets))

    def _run_shodan(self, target: str) -> list[ReconHit]:
        shodan_bin = os.environ.get("SHODAN_BIN", "shodan")
        proc = run_cli([shodan_bin, "host", target, "--format", "json"], timeout=self.timeout * 8)
        if not proc:
            return []
        output = (proc.stdout or "").strip()
        if not output:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        hits: list[ReconHit] = []
        for item in data.get("data", []):
            port = item.get("port")
            product = item.get("product") or item.get("_shodan", {}).get("module", "")
            vulns = item.get("vulns") or []
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=f"{target}:{port} {product}".strip(),
                source_module=self.name,
                source_detail=f"shodan:port:{port}",
                confidence=0.75,
                raw_record=item,
                timestamp=datetime.now().isoformat(),
                cross_refs=[target] + list(vulns)[:5],
            ))
        return hits
