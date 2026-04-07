"""OpenDataBotAdapter — Ukrainian business-registry (ЄДР) deanonymisation."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any

from adapters.base import ReconAdapter, ReconHit, extract_validated_phones
from config import REQUIRE_PROXY

log = logging.getLogger("hanna.recon")


class OpenDataBotAdapter(ReconAdapter):
    """
    Ukrainian business-registry (ЄДР) deanonymisation adapter.

    Links a person's name/phone to registered businesses (ТОВ) and
    sole proprietors (ФОП) via OpenDataBot, returning legal name,
    ЄДРПОУ/ІПН, registered address, role (CEO/founder/beneficiary),
    activities, and registration status.

    Dual strategy:
      1. **Web search** — scrape opendatabot.ua/search?q=Name (no key)
      2. **API enrich** — /company/{code}, /fop/{code}, /person/{code}
         for full data when OPENDATABOT_API_KEY is set

    Phone cross-match against known_phones yields near-certain deanon.

    Env vars
    --------
    OPENDATABOT_API_KEY  — API key (optional, free trial available)
    """

    name = "opendatabot"
    region = "ua"

    _SEARCH_URL = "https://opendatabot.ua/"
    _API_BASE = "https://opendatabot.com/api/v4"

    # ── entry-point ──

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        api_key = os.environ.get("OPENDATABOT_API_KEY", "").strip()
        hits: list[ReconHit] = []

        # Strategy 1: web scrape for name ──────────────────────
        entities = self._web_search(target_name)

        # Strategy 2: API enrichment of found entities ─────────
        for ent in entities:
            code = ent.get("code", "")
            if api_key and code:
                enriched = self._api_lookup(code, ent.get("entity_type", "company"), api_key)
                if enriched:
                    ent.update(enriched)

            hit = self._entity_to_hit(ent, target_name, known_phones)
            if hit:
                hits.append(hit)

        # Strategy 3: API person lookup for name variants ──────
        if api_key:
            # Try Cyrillic transliterations as person search
            for ipn in self._extract_ipn_from_hits(hits):
                person_hits = self._api_person_roles(ipn, target_name, api_key)
                hits.extend(person_hits)

        return self._dedup_by_code(hits)

    # ── web scrape ──

    def _web_search(self, query: str) -> list[dict[str, Any]]:
        """Scrape opendatabot.ua for companies/FOPs matching query.

        OpenDataBot is a Nuxt.js SPA — plain HTTP returns an empty shell.
        Strategy: Playwright first → DDG site-search fallback → static fetch.
        """
        encoded = urllib.parse.quote(query)
        url = f"{self._SEARCH_URL}?q={encoded}"

        body = ""
        if REQUIRE_PROXY and not self.proxy:
            raise RuntimeError("HANNA_REQUIRE_PROXY=1 but no proxy provided to opendatabot")
        # Strategy A: Playwright (renders JS SPA)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                    proxy={"server": self.proxy} if self.proxy else None,
                )
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(2000)  # give Vue/Nuxt hydration time
                body = page.content()
                browser.close()
        except Exception:
            pass

        entities = self._parse_search_html(body, query) if body else []

        # Strategy B: DuckDuckGo site-search fallback (no JS needed)
        if not entities:
            entities = self._ddg_site_search(query)

        return entities

    def _ddg_site_search(self, query: str) -> list[dict[str, Any]]:
        """Search DDG for 'site:opendatabot.ua "name"' and extract codes from URLs."""
        encoded = urllib.parse.quote(f'site:opendatabot.ua "{query}"')
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        status, body = self._fetch(url, headers={"Accept": "text/html"})
        if status != 200 or not body:
            return []

        entities: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Extract opendatabot URLs from DDG snippets
        for m in re.finditer(r'opendatabot\.ua/c/(\d{5,10})', body):
            code = m.group(1)
            if code not in seen:
                seen.add(code)
                entities.append({"code": code, "name": query, "entity_type": "company", "source": "ddg_site_search"})

        for m in re.finditer(r'opendatabot\.ua/fop/(\d{8,10})', body):
            code = m.group(1)
            if code not in seen:
                seen.add(code)
                entities.append({"code": code, "name": query, "entity_type": "fop", "source": "ddg_site_search"})

        for m in re.finditer(r'opendatabot\.ua/p/([a-z0-9\-]{5,80})', body, re.IGNORECASE):
            slug = m.group(1)
            if slug not in seen:
                seen.add(slug)
                entities.append({"code": slug, "name": query, "entity_type": "person", "source": "ddg_site_search"})

        return entities[:20]

    def _parse_search_html(self, html: str, query: str) -> list[dict[str, Any]]:
        """
        Extract entity cards from OpenDataBot search results HTML.
        Looks for company/FOP links: /c/{code} for companies, /fop/{code} for FOPs.
        """
        entities: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        # Pattern 1: company links /c/{ЄДРПОУ}
        for m in re.finditer(
            r'href="/c/(\d{5,10})"[^>]*>([^<]{3,120})</a>',
            html,
        ):
            code, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if code not in seen_codes and name:
                seen_codes.add(code)
                entities.append({
                    "code": code, "name": name,
                    "entity_type": "company", "source": "web_search",
                })

        # Pattern 2: FOP links /fop/{ІПН}
        for m in re.finditer(
            r'href="/fop/(\d{8,10})"[^>]*>([^<]{3,120})</a>',
            html,
        ):
            code, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if code not in seen_codes and name:
                seen_codes.add(code)
                entities.append({
                    "code": code, "name": name,
                    "entity_type": "fop", "source": "web_search",
                })

        # Pattern 3: person profile links /p/{slug} (Nuxt SPA rendered)
        for m in re.finditer(
            r'href="/p/([a-z0-9\-]{5,80})"[^>]*>([^<]{3,120})</a>',
            html, re.IGNORECASE,
        ):
            slug, name = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if slug not in seen_codes and name:
                seen_codes.add(slug)
                entities.append({
                    "code": slug, "name": name,
                    "entity_type": "person", "source": "web_search",
                })

        return entities[:20]

    # ── API methods ──

    def _api_lookup(self, code: str, entity_type: str, api_key: str) -> dict[str, Any]:
        """Fetch full registration data for a company or FOP."""
        if entity_type == "fop":
            endpoint = f"{self._API_BASE}/fop/{code}"
        else:
            endpoint = f"{self._API_BASE}/company/{code}"

        status, body = self._fetch(
            f"{endpoint}?apiKey={api_key}",
            headers={"Accept": "application/json"},
        )
        if status != 200 or not body:
            return {}
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {}

        usr = data.get("USR", {})
        result: dict[str, Any] = {}

        if entity_type == "fop":
            result["full_name"] = usr.get("fullName") or data.get("fullName", "")
            result["address"] = usr.get("location", "")
            result["status"] = usr.get("status", "")
            result["registration_date"] = usr.get("registrationDate", "")
            result["birth_date"] = usr.get("birthDate", "")
            result["primary_activity"] = usr.get("primaryActivity", "")
            result["phones"] = usr.get("phones", [])
            result["email"] = usr.get("email", "")
        else:
            result["full_name"] = usr.get("fullName") or data.get("companyName", "")
            result["short_name"] = usr.get("shortName", "")
            result["ceo"] = usr.get("ceoName", "")
            result["address"] = usr.get("location", "")
            result["status"] = usr.get("status", "")
            result["registration_date"] = usr.get("registrationDate", "")
            result["primary_activity"] = usr.get("primaryActivity", "")
            result["capital"] = usr.get("capital", 0)
            result["phones"] = usr.get("phones", [])
            result["heads"] = [
                {"name": h.get("name", ""), "role": h.get("role", "")}
                for h in usr.get("heads", [])
            ]
            result["beneficiaries"] = [
                {"name": b.get("name", ""), "role": b.get("role", "")}
                for b in usr.get("beneficiaries", [])
            ]

        return result

    def _api_person_roles(
        self, ipn: str, target_name: str, api_key: str,
    ) -> list[ReconHit]:
        """Fetch all business roles for a person by ІПН."""
        url = f"{self._API_BASE}/person/{ipn}?apiKey={api_key}"
        status, body = self._fetch(url, headers={"Accept": "application/json"})
        if status != 200 or not body:
            return []
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []

        hits: list[ReconHit] = []
        usr_roles = data.get("USRRoles", {})

        for role_type in ("ceo", "founder", "fop", "beneficiary", "assignee"):
            items = usr_roles.get(role_type, [])
            if not isinstance(items, list):
                continue
            for item in items[:10]:
                company_code = item.get("code", "")
                company_name = item.get("name", "")
                state_text = item.get("stateText", "")
                if not company_code:
                    continue
                hits.append(ReconHit(
                    observable_type="business_role",
                    value=f"{role_type}@{company_code}",
                    source_module=self.name,
                    source_detail=f"person_roles:{role_type}",
                    confidence=0.85,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "ipn": ipn, "role": role_type,
                        "company_code": company_code,
                        "company_name": company_name,
                        "state": state_text,
                    },
                    cross_refs=[target_name, ipn],
                ))
        return hits

    # ── hit conversion ──

    def _entity_to_hit(
        self, ent: dict[str, Any], target_name: str,
        known_phones: list[str],
    ) -> ReconHit | None:
        code = ent.get("code", "")
        name = ent.get("name", "") or ent.get("full_name", "")
        if not code or not name:
            return None

        entity_type = ent.get("entity_type", "company")
        confidence = 0.6
        source_detail = f"edr_{entity_type}"

        # Name match scoring — try both original and Cyrillic transliterations
        from translit import transliterate_to_cyrillic as _transliterate_to_cyrillic
        name_parts = {p.lower() for p in target_name.split() if len(p) > 2}
        cyrillic_parts: set[str] = set()
        for variant in _transliterate_to_cyrillic(target_name):
            cyrillic_parts.update(p.lower() for p in variant.split() if len(p) > 2)
        all_parts = name_parts | cyrillic_parts
        entity_name_lower = name.lower()
        ceo_name = ent.get("ceo", "").lower()
        combined = f"{entity_name_lower} {ceo_name}"
        name_matches = sum(1 for p in all_parts if p in combined)

        if name_parts and name_matches >= len(name_parts):
            confidence = 0.8   # full name match
        elif name_matches > 0:
            confidence = 0.65  # partial match
        else:
            confidence = 0.45  # code found but name mismatch

        # Phone cross-match — near-certain deanon
        entity_phones = self._normalize_phones(ent.get("phones", []))
        known_norm = self._normalize_phones(known_phones)
        phone_overlap = entity_phones & known_norm
        if phone_overlap:
            confidence = 0.95
            source_detail = f"edr_{entity_type}:phone_match"

        raw_record: dict[str, Any] = {
            "code": code,
            "entity_type": entity_type,
            "name": name,
            "address": ent.get("address", ""),
            "status": ent.get("status", ""),
            "registration_date": ent.get("registration_date", ""),
            "primary_activity": ent.get("primary_activity", ""),
            "source": ent.get("source", ""),
        }
        if entity_type == "company":
            raw_record["ceo"] = ent.get("ceo", "")
            raw_record["capital"] = ent.get("capital", 0)
            raw_record["heads"] = ent.get("heads", [])
            raw_record["beneficiaries"] = ent.get("beneficiaries", [])
        if phone_overlap:
            raw_record["matched_phones"] = list(phone_overlap)
        if ent.get("phones"):
            raw_record["phones"] = ent["phones"]

        return ReconHit(
            observable_type="business_entity",
            value=f"{entity_type}:{code}",
            source_module=self.name,
            source_detail=source_detail,
            confidence=round(confidence, 2),
            timestamp=datetime.now().isoformat(),
            raw_record=raw_record,
            cross_refs=[target_name] + list(phone_overlap),
        )

    # ── helpers ──

    @staticmethod
    def _normalize_phones(phones: list[str]) -> set[str]:
        """Strip non-digit chars and normalize to last 10 digits."""
        out: set[str] = set()
        for p in phones:
            digits = re.sub(r"\D", "", str(p))
            if len(digits) >= 10:
                out.add(digits[-10:])
        return out

    @staticmethod
    def _extract_ipn_from_hits(hits: list[ReconHit]) -> list[str]:
        """Pull any ІПН-like codes from FOP hits."""
        ipns: list[str] = []
        for h in hits:
            code = h.raw_record.get("code", "")
            if h.raw_record.get("entity_type") == "fop" and len(code) == 10:
                ipns.append(code)
        return ipns[:5]

    @staticmethod
    def _dedup_by_code(hits: list[ReconHit]) -> list[ReconHit]:
        """Keep highest-confidence hit per business code."""
        best: dict[str, ReconHit] = {}
        for h in hits:
            code = h.raw_record.get("code") or h.raw_record.get("company_code") or h.value
            existing = best.get(code)
            if not existing or h.confidence > existing.confidence:
                best[code] = h
        return list(best.values())
