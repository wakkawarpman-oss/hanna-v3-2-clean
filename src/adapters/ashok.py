"""AshokAdapter — Infrastructure reconnaissance tool integration."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime

from adapters.base import (
    ReconAdapter,
    ReconHit,
    extract_validated_phones,
)
from adapters.cli_common import run_cli


class AshokAdapter(ReconAdapter):
    """
    Ashok — infrastructure reconnaissance tool integration.

    Capabilities:
      - Subdomain enumeration  (--subdomain)
      - CMS & headers analysis (detect WP, Joomla, analytics IDs)
      - Wayback Machine integration (archived pages, old contacts)
      - Google Analytics UA-ID reverse lookup for cross-site pivoting

    Filters: excludes common platforms (google.com, facebook.com, etc.)

    Requires: pip install ashok  (or git clone + setup.py)
    Env vars:
      ASHOK_BIN  — path to ashok executable (default: "ashok")
    """

    name = "ashok"
    region = "global"

    _IGNORE_DOMAINS = {
        "google.com", "facebook.com", "twitter.com", "instagram.com",
        "youtube.com", "linkedin.com", "github.com", "microsoft.com",
        "apple.com", "amazon.com", "cloudflare.com", "amazonaws.com",
        "googleusercontent.com", "gstatic.com", "fbcdn.net",
    }

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Extract domains from known usernames (could be domain-like)
        domains = self._extract_target_domains(target_name, known_usernames)

        for domain in domains:
            # 1. Subdomain enumeration
            hits.extend(self._enumerate_subdomains(domain))

            # 2. CMS & headers analysis
            hits.extend(self._analyze_headers(domain))

            # 3. Wayback Machine archived pages
            hits.extend(self._search_wayback(domain, target_name))

        # 4. Wayback search by name (not domain)
        hits.extend(self._search_wayback_by_name(target_name))

        return hits

    def _extract_target_domains(self, target_name: str, known_usernames: list[str]) -> list[str]:
        """Extract plausible domains from usernames or derive from target name."""
        domains: list[str] = []
        for uname in known_usernames:
            # If username looks like a domain
            if "." in uname and not uname.startswith("@"):
                base = uname.lower().split("/")[0]
                if base not in self._IGNORE_DOMAINS:
                    domains.append(base)
        # Also try common personal site patterns (ASCII only — skip Cyrillic names)
        name_slug = target_name.lower().replace(" ", "")
        if name_slug.isascii():
            for tld in [".com", ".ua", ".me"]:
                domains.append(f"{name_slug}{tld}")
        return domains[:5]

    def _run_ashok_cli(self, args: list[str]) -> str | None:
        """Run Ashok CLI tool with given arguments."""
        ashok_bin = os.environ.get("ASHOK_BIN", "ashok")
        cmd = [ashok_bin] + args
        proc = run_cli(cmd, timeout=self.timeout * 5, proxy=self.proxy)
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        return None

    def _enumerate_subdomains(self, domain: str) -> list[ReconHit]:
        """Subdomain enumeration via Ashok CLI or crt.sh fallback."""
        hits: list[ReconHit] = []

        # Try Ashok CLI first
        output = self._run_ashok_cli(["--subdomain", domain])
        if output:
            for line in output.splitlines():
                sub = line.strip().lower()
                if sub and "." in sub and not any(ign in sub for ign in self._IGNORE_DOMAINS):
                    hits.append(ReconHit(
                        observable_type="infrastructure",
                        value=sub,
                        source_module=self.name,
                        source_detail=f"subdomain_enum:{domain}",
                        confidence=0.5,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "subdomain": sub},
                    ))
            return hits

        # Fallback: crt.sh certificate transparency search
        url = f"https://crt.sh/?q=%.{urllib.parse.quote(domain)}&output=json"
        status, body = self._fetch(url)
        if status == 200 and body:
            try:
                certs = json.loads(body)
                seen: set[str] = set()
                for cert in certs[:100]:
                    name_value = cert.get("name_value", "")
                    for sub in name_value.split("\n"):
                        sub = sub.strip().lower().lstrip("*.")
                        if sub and sub not in seen and sub != domain:
                            seen.add(sub)
                            if not any(ign in sub for ign in self._IGNORE_DOMAINS):
                                hits.append(ReconHit(
                                    observable_type="infrastructure",
                                    value=sub,
                                    source_module=self.name,
                                    source_detail=f"crt.sh:{domain}",
                                    confidence=0.45,
                                    timestamp=datetime.now().isoformat(),
                                    raw_record=cert,
                                ))
            except (json.JSONDecodeError, TypeError):
                pass

        return hits

    def _analyze_headers(self, domain: str) -> list[ReconHit]:
        """Fetch HTTP headers and detect CMS, analytics IDs, tech stack."""
        hits: list[ReconHit] = []
        for scheme in ("https", "http"):
            url = f"{scheme}://{domain}/"
            status, body = self._fetch(url)
            if status == 0:
                continue

            # Extract Google Analytics UA-IDs (cross-site correlation pivot)
            ua_ids = re.findall(r'UA-\d{4,10}-\d{1,4}', body)
            for ua_id in set(ua_ids):
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=ua_id,
                    source_module=self.name,
                    source_detail=f"analytics_id:{domain}",
                    confidence=0.65,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "analytics_id": ua_id, "type": "google_analytics"},
                ))

            # Detect GA4 measurement IDs
            ga4_ids = re.findall(r'G-[A-Z0-9]{10,12}', body)
            for ga4 in set(ga4_ids):
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=ga4,
                    source_module=self.name,
                    source_detail=f"ga4_id:{domain}",
                    confidence=0.65,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "analytics_id": ga4, "type": "ga4"},
                ))

            # CMS detection
            cms = self._detect_cms(body)
            if cms:
                hits.append(ReconHit(
                    observable_type="infrastructure",
                    value=f"cms:{cms}@{domain}",
                    source_module=self.name,
                    source_detail=f"cms_detect:{domain}",
                    confidence=0.5,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "cms": cms},
                ))

            # Extract emails from page body
            emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', body)
            for email in set(emails):
                email = email.lower()
                if "noreply" not in email and "example" not in email and "wixpress" not in email:
                    hits.append(ReconHit(
                        observable_type="email",
                        value=email,
                        source_module=self.name,
                        source_detail=f"page_scrape:{domain}",
                        confidence=0.4,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "email": email},
                    ))

            # Extract phones from page
            phones = extract_validated_phones(body)
            for phone in phones:
                hits.append(ReconHit(
                    observable_type="phone",
                    value=phone,
                    source_module=self.name,
                    source_detail=f"page_scrape:{domain}",
                    confidence=0.4,
                    timestamp=datetime.now().isoformat(),
                    raw_record={"domain": domain, "phone": phone},
                ))

            break  # only need one scheme to succeed

        return hits

    @staticmethod
    def _detect_cms(html: str) -> str | None:
        """Detect CMS from HTML content signatures."""
        lower = html.lower()
        if "wp-content" in lower or "wordpress" in lower:
            return "wordpress"
        if "joomla" in lower:
            return "joomla"
        if "drupal" in lower:
            return "drupal"
        if "bitrix" in lower or "1c-bitrix" in lower:
            return "bitrix"
        if "tilda" in lower or "tildacdn" in lower:
            return "tilda"
        if "wix.com" in lower:
            return "wix"
        if "squarespace" in lower:
            return "squarespace"
        if "shopify" in lower:
            return "shopify"
        return None

    def _search_wayback(self, domain: str, target_name: str) -> list[ReconHit]:
        """Search Wayback Machine for archived pages with contact info."""
        hits: list[ReconHit] = []

        # Keep P0 breadth bounded: probe the highest-signal pages first.
        pages = ["about", "contact", "cv"]
        for page_slug in pages:
            cdx_url = (
                f"https://web.archive.org/cdx/search/cdx?"
                f"url={urllib.parse.quote(domain)}/{page_slug}*"
                f"&output=json&fl=timestamp,original&limit=3&collapse=urlkey"
            )
            status, body = self._fetch(cdx_url)
            if status != 200 or not body:
                continue

            try:
                rows = json.loads(body)
                for row in rows[1:]:  # skip header
                    ts, orig_url = row[0], row[1]
                    wb_url = f"https://web.archive.org/web/{ts}/{orig_url}"
                    hits.append(ReconHit(
                        observable_type="url",
                        value=wb_url,
                        source_module=self.name,
                        source_detail=f"wayback:{domain}/{page_slug}",
                        confidence=0.35,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"domain": domain, "timestamp": ts, "url": orig_url, "wayback_url": wb_url},
                    ))
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        return hits

    def _search_wayback_by_name(self, target_name: str) -> list[ReconHit]:
        """Search Wayback CDX for any URL containing the target name."""
        hits: list[ReconHit] = []
        name_slug = target_name.lower().replace(" ", "-")
        alt_slug = target_name.lower().replace(" ", "_")

        for slug in (name_slug, alt_slug):
            cdx_url = (
                f"https://web.archive.org/cdx/search/cdx?"
                f"url=*{urllib.parse.quote(slug)}*"
                f"&output=json&fl=timestamp,original&limit=3&collapse=urlkey"
            )
            status, body = self._fetch(cdx_url)
            if status != 200 or not body:
                continue
            try:
                rows = json.loads(body)
                for row in rows[1:]:
                    ts, orig_url = row[0], row[1]
                    wb_url = f"https://web.archive.org/web/{ts}/{orig_url}"
                    hits.append(ReconHit(
                        observable_type="url",
                        value=wb_url,
                        source_module=self.name,
                        source_detail=f"wayback_name_search:{slug}",
                        confidence=0.3,
                        timestamp=datetime.now().isoformat(),
                        raw_record={"slug": slug, "timestamp": ts, "url": orig_url},
                    ))
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        return hits
