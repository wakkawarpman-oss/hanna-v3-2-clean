"""MaryamAdapter — OWASP Maryam OSINT framework integration."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime

from adapters.base import DependencyUnavailableError, MissingBinaryError, ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class MaryamAdapter(ReconAdapter):
    """
    OWASP Maryam — modular OSINT framework integration.

    Wraps the `maryam` CLI to run modules:
      - dns_search:   DNS enumeration for domains associated with target
      - email_search: Email discovery via search-engine dorking
      - social_nets:  Social network profile discovery
      - web_search:   Alternative search engines (DuckDuckGo, Bing, Yahoo)

    Primary purpose: re-check soft_match links through alternative
    search engines to confirm or kill them.

    Requires: pip install maryam  (or git clone + setup.py)
    """

    name = "maryam"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Search by target name via web_search module
        hits.extend(self._run_web_search(target_name))

        # 2. Search by known usernames (alternative engine verification)
        for username in known_usernames:
            hits.extend(self._run_web_search(username))

        # 3. Email search — dorking for associated emails
        hits.extend(self._run_email_search(target_name))

        # 4. Social nets scan
        for username in known_usernames:
            hits.extend(self._run_social_nets(username))

        return hits

    def _run_maryam_module(self, module: str, query: str) -> str | None:
        """Execute a Maryam module via CLI and capture JSON output."""
        maryam_bin = os.environ.get("MARYAM_BIN", "maryam")
        cmd = [maryam_bin, "-e", module, "-q", query, "-o", "json"]
        try:
            proc = run_cli(cmd, timeout=self.timeout * 3, proxy=self.proxy)
        except (MissingBinaryError, DependencyUnavailableError):
            return None
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        return None

    def _run_web_search(self, query: str) -> list[ReconHit]:
        """Search alternative engines (DuckDuckGo, Bing) for the target."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("web_search", query)
        if not output:
            # Fallback: direct DuckDuckGo HTML search
            return self._fallback_ddg_search(query)

        try:
            data = json.loads(output)
            results = data if isinstance(data, list) else data.get("results", [])
            for item in results[:20]:
                url = item.get("url", item.get("link", ""))
                if url:
                    hits.append(ReconHit(
                        observable_type="url",
                        value=url,
                        source_module=self.name,
                        source_detail=f"web_search:{query[:30]}",
                        confidence=0.35,
                        timestamp=datetime.now().isoformat(),
                        raw_record=item,
                        cross_refs=[query],
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits

    def _fallback_ddg_search(self, query: str) -> list[ReconHit]:
        """Direct DuckDuckGo HTML scrape when Maryam is unavailable."""
        hits: list[ReconHit] = []
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status != 200 or not body:
            return hits

        # Extract result links from DDG HTML
        link_pattern = re.compile(r'class="result__a"[^>]*href="([^"]+)"')
        for m in link_pattern.finditer(body):
            href = m.group(1)
            # DDG wraps links in redirects — extract actual URL
            parsed = urllib.parse.urlparse(href)
            params = urllib.parse.parse_qs(parsed.query)
            actual = params.get("uddg", [href])[0]
            if actual.startswith("http"):
                hits.append(ReconHit(
                    observable_type="url",
                    value=actual,
                    source_module=self.name,
                    source_detail=f"ddg_fallback:{query[:30]}",
                    confidence=0.3,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"query": query, "url": actual},
                    cross_refs=[query],
                ))
        return hits[:15]

    def _run_email_search(self, query: str) -> list[ReconHit]:
        """Dork for emails associated with a name/domain."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("email_search", query)
        if not output:
            return hits
        try:
            data = json.loads(output)
            emails = data if isinstance(data, list) else data.get("emails", [])
            for email_val in emails:
                email_str = email_val if isinstance(email_val, str) else email_val.get("email", "")
                if "@" in email_str and "noreply" not in email_str.lower():
                    hits.append(ReconHit(
                        observable_type="email",
                        value=email_str.lower(),
                        source_module=self.name,
                        source_detail=f"email_search:{query[:30]}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"query": query, "email": email_str},
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits

    def _run_social_nets(self, username: str) -> list[ReconHit]:
        """Check social networks for a username."""
        hits: list[ReconHit] = []
        output = self._run_maryam_module("social_nets", username)
        if not output:
            return hits
        try:
            data = json.loads(output)
            profiles = data if isinstance(data, list) else data.get("profiles", data.get("results", []))
            for profile in profiles[:30]:
                url = profile.get("url", profile.get("link", "")) if isinstance(profile, dict) else str(profile)
                if url and url.startswith("http"):
                    hits.append(ReconHit(
                        observable_type="url",
                        value=url,
                        source_module=self.name,
                        source_detail=f"social_nets:{username}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record=profile if isinstance(profile, dict) else {"url": url},
                        cross_refs=[username],
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits
