"""KatanaAdapter — web crawling and endpoint discovery via ProjectDiscovery katana."""
from __future__ import annotations

import json
import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class KatanaAdapter(ReconAdapter):
    """Discover URLs, endpoints, JS references, and forms through crawling."""

    name = "katana"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for target in self._collect_targets(target_name, known_usernames)[:5]:
            hits.extend(self._crawl(target))
        return hits

    def _collect_targets(self, target_name: str, known_usernames: list[str]) -> list[str]:
        targets: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                targets.append(value)
            elif "." in value and " " not in value and "@" not in value:
                targets.append(f"https://{value}")
        return list(dict.fromkeys(targets))

    def _crawl(self, target: str) -> list[ReconHit]:
        katana_bin = os.environ.get("KATANA_BIN", "katana")
        proc = run_cli(
            [
                katana_bin,
                "-u", target,
                "-j",
                "-silent",
                "-d", "3",
                "-timeout", str(int(self.timeout)),
            ],
            timeout=self.timeout * 8,
            proxy=self.proxy,
            proxy_cli_flag="-proxy",
        )
        if not proc or not proc.stdout.strip():
            return []

        hits: list[ReconHit] = []
        seen: set[str] = set()
        for line in proc.stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = obj.get("request", {}).get("endpoint") or obj.get("url") or obj.get("endpoint")
            if not url or url in seen:
                continue
            seen.add(url)
            detail_bits = []
            if obj.get("response", {}).get("status_code"):
                detail_bits.append(str(obj["response"]["status_code"]))
            if obj.get("source"):
                detail_bits.append(str(obj["source"]))
            if obj.get("tag"):
                detail_bits.append(str(obj["tag"]))
            hits.append(ReconHit(
                observable_type="url",
                value=url,
                source_module=self.name,
                source_detail=f"katana:{':'.join(detail_bits) or 'crawl'}",
                confidence=0.55,
                raw_record=obj,
                timestamp=datetime.now().isoformat(),
                cross_refs=[target],
            ))
        return hits
