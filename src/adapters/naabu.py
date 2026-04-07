"""NaabuAdapter — fast port discovery via ProjectDiscovery naabu."""
from __future__ import annotations

import json
import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class NaabuAdapter(ReconAdapter):
    """Fast port scan for domains and IPs."""

    name = "naabu"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for target in self._collect_targets(target_name, known_usernames)[:10]:
            hits.extend(self._scan(target))
        return hits

    def _collect_targets(self, target_name: str, known_usernames: list[str]) -> list[str]:
        targets: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip()
            if not value or "@" in value or " " in value:
                continue
            if value.startswith(("http://", "https://")):
                value = value.split("://", 1)[1].split("/", 1)[0]
            if "." in value or value.replace(".", "").isdigit():
                targets.append(value)
        return list(dict.fromkeys(targets))

    def _scan(self, target: str) -> list[ReconHit]:
        naabu_bin = os.environ.get("NAABU_BIN", "naabu")
        proc = run_cli(
            [naabu_bin, "-host", target, "-json", "-silent", "-rate", "1000", "-timeout", str(int(self.timeout))],
            timeout=self.timeout * 6,
            proxy=self.proxy,
            proxy_cli_flag="-proxy",
        )
        if not proc or not proc.stdout.strip():
            return []
        hits: list[ReconHit] = []
        for line in proc.stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            host = obj.get("host") or target
            port = obj.get("port")
            if not port:
                continue
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=f"{host}:{port}",
                source_module=self.name,
                source_detail=f"naabu:port:{port}",
                confidence=0.72,
                raw_record=obj,
                timestamp=datetime.now().isoformat(),
                cross_refs=[target],
            ))
        return hits
