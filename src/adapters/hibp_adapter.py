"""HIBPAdapter — breach and paste enrichment for email addresses via HIBP v3."""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime

from adapters.base import MissingCredentialsError, ReconAdapter, ReconHit


class HIBPAdapter(ReconAdapter):
    """Enrich email pivots with breach and paste exposure from HIBP."""

    name = "hibp"
    region = "global"

    _API_BASE = "https://haveibeenpwned.com/api/v3"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        api_key = os.environ.get("HIBP_API_KEY", "").strip()
        if not api_key:
            raise MissingCredentialsError("HIBP_API_KEY")

        hits: list[ReconHit] = []
        emails = self._collect_emails(target_name, known_usernames)
        if not emails:
            self._record_noop("no email observables available for HIBP")
            return hits
        for email in emails[:5]:
            hits.extend(self._query_breaches(email, api_key))
            hits.extend(self._query_pastes(email, api_key))
        return hits

    def _collect_emails(self, target_name: str, known_usernames: list[str]) -> list[str]:
        candidates = [target_name, *known_usernames]
        emails: list[str] = []
        for value in candidates:
            email = value.strip().lower()
            if not email or "@" not in email or " " in email:
                continue
            emails.append(email)
        return list(dict.fromkeys(emails))

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "hibp-api-key": api_key,
            "user-agent": os.environ.get("HIBP_USER_AGENT", "HANNA/2026"),
            "accept": "application/json",
        }

    def _query_breaches(self, email: str, api_key: str) -> list[ReconHit]:
        url = f"{self._API_BASE}/breachedaccount/{urllib.parse.quote(email)}?truncateResponse=false"
        status, body = self._fetch(url, headers=self._headers(api_key))
        if status in {0, 404} or not body:
            return []
        try:
            rows = json.loads(body)
        except json.JSONDecodeError:
            return []

        hits: list[ReconHit] = []
        for item in rows:
            name = item.get("Name") or item.get("Title") or "unknown"
            domain = item.get("Domain") or ""
            data_classes = item.get("DataClasses") or []
            flags = {
                "is_verified": bool(item.get("IsVerified")),
                "is_sensitive": bool(item.get("IsSensitive")),
                "is_malware": bool(item.get("IsMalware")),
                "is_stealer_log": bool(item.get("IsStealerLog")),
            }
            confidence = 0.78
            if flags["is_verified"]:
                confidence = 0.86
            if flags["is_sensitive"] or flags["is_malware"] or flags["is_stealer_log"]:
                confidence = min(0.95, confidence + 0.05)
            detail = f"hibp:breach:{name}"
            if domain:
                detail = f"{detail}@{domain}"
            hits.append(ReconHit(
                observable_type="email",
                value=email,
                source_module=self.name,
                source_detail=detail,
                confidence=confidence,
                raw_record={
                    "email": email,
                    "name": name,
                    "domain": domain,
                    "breach_date": item.get("BreachDate"),
                    "added_date": item.get("AddedDate"),
                    "data_classes": data_classes,
                    **flags,
                },
                timestamp=datetime.now().isoformat(),
                cross_refs=[email, *(data_classes[:5] if isinstance(data_classes, list) else [])],
            ))
        return hits

    def _query_pastes(self, email: str, api_key: str) -> list[ReconHit]:
        url = f"{self._API_BASE}/pasteaccount/{urllib.parse.quote(email)}"
        status, body = self._fetch(url, headers=self._headers(api_key))
        if status in {0, 404} or not body:
            return []
        try:
            rows = json.loads(body)
        except json.JSONDecodeError:
            return []

        hits: list[ReconHit] = []
        for item in rows:
            source = item.get("Source") or "paste"
            paste_id = item.get("Id") or "unknown"
            hits.append(ReconHit(
                observable_type="email",
                value=email,
                source_module=self.name,
                source_detail=f"hibp:paste:{source}:{paste_id}",
                confidence=0.62,
                raw_record={
                    "email": email,
                    "source": source,
                    "id": paste_id,
                    "title": item.get("Title"),
                    "date": item.get("Date"),
                    "email_count": item.get("EmailCount"),
                },
                timestamp=datetime.now().isoformat(),
                cross_refs=[email],
            ))
        return hits