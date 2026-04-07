"""SocialAnalyzerAdapter — 1000+ social network username search."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import run_cli


class SocialAnalyzerAdapter(ReconAdapter):
    """
    Social-Analyzer — 1000+ social network username search.

    More aggressive than Maigret/Sherlock. Checks:
      - 1000+ social platforms simultaneously
      - Returns profile URL, name, existence confidence
      - CLI + JSON output mode

    Requires: pip install social-analyzer
    Env vars:
      SOCIAL_ANALYZER_BIN — path to executable (default: "social-analyzer")
    """

    name = "social_analyzer"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        for username in known_usernames:
            results = self._run_social_analyzer(username)
            if results:
                hits.extend(results)
            else:
                # Fallback: direct checks on key platforms
                hits.extend(self._fallback_platform_checks(username))

        return hits

    def _run_social_analyzer(self, username: str) -> list[ReconHit] | None:
        """Run social-analyzer CLI for a username."""
        sa_bin = os.environ.get("SOCIAL_ANALYZER_BIN", "social-analyzer")
        cmd = [
            sa_bin,
            "--username", username,
            "--metadata",
            "--output", "json",
        ]
        proc = run_cli(cmd, timeout=self.timeout * 10, proxy=self.proxy)
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return self._parse_sa_output(username, proc.stdout.strip())
        return None

    def _parse_sa_output(self, username: str, output: str) -> list[ReconHit]:
        """Parse social-analyzer JSON output."""
        hits: list[ReconHit] = []
        try:
            data = json.loads(output)
            profiles = data if isinstance(data, list) else data.get("detected", data.get("results", []))
            for profile in profiles:
                if isinstance(profile, dict):
                    url = profile.get("link", profile.get("url", ""))
                    site = profile.get("site", profile.get("source", ""))
                    status = profile.get("status", "")
                    if url and url.startswith("http") and "not found" not in status.lower():
                        conf = 0.55 if status.lower() in ("found", "claimed", "available") else 0.3
                        hits.append(ReconHit(
                            observable_type="url",
                            value=url,
                            source_module=self.name,
                            source_detail=f"social_analyzer:{site or 'unknown'}",
                            confidence=conf,
                            timestamp=datetime.now().isoformat(),
                            raw_record=profile,
                            cross_refs=[username],
                        ))
        except (json.JSONDecodeError, TypeError):
            pass
        return hits[:50]

    def _fallback_platform_checks(self, username: str) -> list[ReconHit]:
        """Direct HTTP HEAD checks on popular platforms when CLI unavailable."""
        hits: list[ReconHit] = []
        platforms = {
            "tiktok": f"https://www.tiktok.com/@{urllib.parse.quote(username, safe='')}",
            "pinterest": f"https://www.pinterest.com/{urllib.parse.quote(username, safe='')}/",
            "reddit": f"https://www.reddit.com/user/{urllib.parse.quote(username, safe='')}",
            "medium": f"https://medium.com/@{urllib.parse.quote(username, safe='')}",
            "deviantart": f"https://www.deviantart.com/{urllib.parse.quote(username, safe='')}",
            "soundcloud": f"https://soundcloud.com/{urllib.parse.quote(username, safe='')}",
            "twitch": f"https://www.twitch.tv/{urllib.parse.quote(username, safe='')}",
            "vimeo": f"https://vimeo.com/{urllib.parse.quote(username, safe='')}",
            "flickr": f"https://www.flickr.com/people/{urllib.parse.quote(username, safe='')}/",
            "ok.ru": f"https://ok.ru/{urllib.parse.quote(username, safe='')}",
            "habr": f"https://habr.com/ru/users/{urllib.parse.quote(username, safe='')}/",
            "pikabu": f"https://pikabu.ru/@{urllib.parse.quote(username, safe='')}",
        }

        for platform, url in platforms.items():
            # Reddit returns 200 for all /user/ URLs (SPA); verify via JSON API
            if platform == "reddit":
                api_url = url.rstrip("/") + "/about.json"
                api_status, _ = self._fetch(api_url)
                if api_status != 200:
                    continue
            status, body = self._fetch(url)
            if status == 200 and body:
                body_lower = body.lower()
                if "page not found" in body_lower or "user not found" in body_lower or "404" in body_lower:
                    continue
                hits.append(ReconHit(
                    observable_type="url",
                    value=url,
                    source_module=self.name,
                    source_detail=f"direct_check:{platform}",
                    confidence=0.35,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"username": username, "platform": platform, "status": status},
                    cross_refs=[username],
                ))

        return hits
