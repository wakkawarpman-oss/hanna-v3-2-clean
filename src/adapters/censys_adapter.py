"""CensysAdapter — host and certificate discovery via Censys Search API."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit


class CensysAdapter(ReconAdapter):
    """Use Censys API for hosts, certificates, and shadow IT discovery."""

    name = "censys"
    region = "global"

    _API_BASE = "https://search.censys.io/api/v2"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        api_id = os.environ.get("CENSYS_API_ID", "").strip()
        api_secret = os.environ.get("CENSYS_API_SECRET", "").strip()
        if not api_id or not api_secret:
            return []

        hits: list[ReconHit] = []
        for query in self._collect_queries(target_name, known_usernames)[:5]:
            hits.extend(self._query_hosts(query, api_id, api_secret))
            hits.extend(self._query_certs(query, api_id, api_secret))
        return hits

    def _collect_queries(self, target_name: str, known_usernames: list[str]) -> list[str]:
        queries: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip().lower()
            if not value or " " in value or value.startswith("+"):
                continue
            if value.startswith(("http://", "https://")):
                value = value.split("://", 1)[1].split("/", 1)[0]
            queries.append(value)
        return list(dict.fromkeys(queries))

    def _request(self, path: str, payload: dict, api_id: str, api_secret: str) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._API_BASE}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HANNA/2026",
            },
            method="POST",
        )
        auth = f"{api_id}:{api_secret}".encode("utf-8")
        import base64
        req.add_header("Authorization", f"Basic {base64.b64encode(auth).decode('ascii')}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 2) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
            return None

    def _query_hosts(self, query: str, api_id: str, api_secret: str) -> list[ReconHit]:
        payload = {"q": query, "per_page": 5}
        data = self._request("/hosts/search", payload, api_id, api_secret)
        if not data:
            return []
        hits: list[ReconHit] = []
        for item in data.get("result", {}).get("hits", []):
            ip = item.get("ip") or ""
            name = item.get("name") or query
            services = item.get("services", [])
            ports = sorted({str(s.get("port")) for s in services if s.get("port")})
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=f"{ip} {name} ports={','.join(ports[:10])}".strip(),
                source_module=self.name,
                source_detail=f"censys:host:{query}",
                confidence=0.78,
                raw_record=item,
                timestamp=datetime.now().isoformat(),
                cross_refs=[query],
            ))
        return hits

    def _query_certs(self, query: str, api_id: str, api_secret: str) -> list[ReconHit]:
        payload = {"q": query, "per_page": 5}
        data = self._request("/certificates/search", payload, api_id, api_secret)
        if not data:
            return []
        hits: list[ReconHit] = []
        for item in data.get("result", {}).get("hits", []):
            names = item.get("names") or []
            parsed = item.get("parsed", {})
            subject = parsed.get("subject_dn", query)
            value = names[0] if names else subject
            hits.append(ReconHit(
                observable_type="infrastructure",
                value=value,
                source_module=self.name,
                source_detail=f"censys:cert:{query}",
                confidence=0.68,
                raw_record=item,
                timestamp=datetime.now().isoformat(),
                cross_refs=[query],
            ))
        return hits
