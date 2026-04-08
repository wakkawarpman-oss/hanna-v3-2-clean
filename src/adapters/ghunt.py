"""GHuntAdapter — Google account reconnaissance."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime

from adapters.base import DependencyUnavailableError, MissingBinaryError, ReconAdapter, ReconHit, extract_validated_phones
from adapters.cli_common import run_cli


class GHuntAdapter(ReconAdapter):
    """
    GHunt — Google account reconnaissance.

    From a known Gmail address, extracts:
      - Google Maps contributions and reviews
      - Public Google Photos albums
      - YouTube channel (if linked)
      - Device information (model/OS from sync metadata)
      - Google Calendar public events

    Requires: pip install ghunt  (+ OAuth cookie setup via ghunt login)
    Env vars:
      GHUNT_BIN       — path to ghunt executable (default: "ghunt")
      GHUNT_CREDS_DIR — directory with ghunt credentials
    """

    name = "ghunt"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Extract emails from known usernames
        emails = [u for u in known_usernames if "@" in u and "gmail" in u.lower()]

        # Also try constructing Gmail from name patterns
        name_parts = target_name.lower().split()
        if len(name_parts) >= 2 and not emails:
            emails.extend([
                f"{name_parts[0]}.{name_parts[1]}@gmail.com",
                f"{name_parts[0]}{name_parts[1]}@gmail.com",
            ])

        for email in emails[:3]:
            ghunt_data = self._run_ghunt_email(email)
            if ghunt_data:
                hits.extend(self._parse_ghunt_output(email, ghunt_data))
            else:
                # Manual fallback: check Google Maps reviews
                hits.extend(self._check_google_maps_profile(email, target_name))

        return hits

    def _run_ghunt_email(self, email: str) -> str | None:
        """Run GHunt CLI to profile a Gmail address."""
        ghunt_bin = os.environ.get("GHUNT_BIN", "ghunt")
        creds = os.environ.get("GHUNT_CREDS_DIR", "")
        cmd = [ghunt_bin, "email", email]
        if creds:
            cmd += ["--creds", creds]
        try:
            proc = run_cli(cmd, timeout=self.timeout * 5, proxy=self.proxy)
        except (MissingBinaryError, DependencyUnavailableError):
            return None
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        return None

    def _parse_ghunt_output(self, email: str, output: str) -> list[ReconHit]:
        """Parse GHunt text output for actionable intelligence."""
        hits: list[ReconHit] = []
        raw = {"email": email, "output_preview": output[:2000]}

        # Look for Google Maps profile
        maps_match = re.search(r'(https://www\.google\.com/maps/contrib/\d+)', output)
        if maps_match:
            hits.append(ReconHit(
                observable_type="url",
                value=maps_match.group(1),
                source_module=self.name,
                source_detail=f"ghunt:maps_contrib:{email}",
                confidence=0.75,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # YouTube channel
        yt_match = re.search(r'(https://www\.youtube\.com/channel/[\w-]+)', output)
        if yt_match:
            hits.append(ReconHit(
                observable_type="url",
                value=yt_match.group(1),
                source_module=self.name,
                source_detail=f"ghunt:youtube:{email}",
                confidence=0.7,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # Google Photos albums
        photos_matches = re.findall(r'(https://photos\.google\.com/[\w/]+)', output)
        for url in photos_matches[:3]:
            hits.append(ReconHit(
                observable_type="url",
                value=url,
                source_module=self.name,
                source_detail=f"ghunt:photos:{email}",
                confidence=0.65,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # Phones in output
        phones = extract_validated_phones(output)
        for phone in phones:
            hits.append(ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail=f"ghunt:phone:{email}",
                confidence=0.6,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
                cross_refs=[email],
            ))

        # If GHunt ran but produced no structured hits, still note it
        if not hits:
            hits.append(ReconHit(
                observable_type="email",
                value=email,
                source_module=self.name,
                source_detail="ghunt:profile_exists",
                confidence=0.3,
                timestamp=datetime.now().isoformat(),
                raw_record=raw,
            ))

        return hits

    def _check_google_maps_profile(self, email: str, target_name: str) -> list[ReconHit]:
        """Fallback: search Google Maps for user reviews by name."""
        hits: list[ReconHit] = []
        encoded = urllib.parse.quote(f'"{target_name}" site:google.com/maps/contrib')
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status == 200 and body:
            maps_links = re.findall(r'https://www\.google\.com/maps/contrib/\d+', body)
            for link in list(set(maps_links))[:2]:
                hits.append(ReconHit(
                    observable_type="url",
                    value=link,
                    source_module=self.name,
                    source_detail=f"maps_search:{target_name}",
                    confidence=0.35,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"query": target_name, "url": link},
                ))
        return hits
