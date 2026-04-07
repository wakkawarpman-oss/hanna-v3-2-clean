"""HttpxAdapter — HTTP probing and web fingerprinting via ProjectDiscovery httpx."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class HttpxAdapter(ReconAdapter):
    """Probe domains/URLs and return live web surface metadata."""

    name = "httpx_probe"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for target in self._collect_targets(target_name, known_usernames)[:10]:
            hits.extend(self._probe_target(target))
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
                targets.append(value)
        return list(dict.fromkeys(targets))

    def _probe_target(self, target: str) -> list[ReconHit]:
        httpx_bin = os.environ.get("HTTPX_BIN", "httpx")
        proc = run_cli(
            [
                httpx_bin,
                "-u", target,
                "-json",
                "-silent",
                "-tech-detect",
                "-title",
                "-status-code",
                "-web-server",
                "-follow-redirects",
                "-timeout", str(int(self.timeout)),
            ],
            timeout=self.timeout * 4,
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

            url = obj.get("url") or obj.get("input") or target
            status = obj.get("status_code")
            title = (obj.get("title") or "").strip()
            webserver = obj.get("webserver") or ""
            technologies = obj.get("tech") or []

            detail = f"httpx:{status}:{webserver or 'web'}"
            value_parts = [url]
            if status:
                value_parts.append(f"status={status}")
            if title:
                value_parts.append(f"title={title[:80]}")
            if technologies:
                value_parts.append(f"tech={','.join(technologies[:5])}")

            hits.append(ReconHit(
                observable_type="infrastructure",
                value=" | ".join(value_parts),
                source_module=self.name,
                source_detail=detail,
                confidence=0.7 if status and 200 <= int(status) < 500 else 0.45,
                raw_record=obj,
                timestamp=datetime.now().isoformat(),
                cross_refs=[target],
            ))

            if obj.get("host"):
                hits.append(ReconHit(
                    observable_type="url",
                    value=url,
                    source_module=self.name,
                    source_detail="httpx:url",
                    confidence=0.6,
                    raw_record=obj,
                    timestamp=datetime.now().isoformat(),
                    cross_refs=[target],
                ))

        return hits
