"""AvitoAdapter — Avito.ru and Yula marketplace scraper."""
from __future__ import annotations

import urllib.parse
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit, extract_validated_phones


class AvitoAdapter(ReconAdapter):
    """Search Avito.ru and Yula for seller profiles."""

    name = "avito"
    region = "ru"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Search Avito by name (public seller names are visible)
        for username in known_usernames:
            encoded = urllib.parse.quote(username)
            url = f"https://www.avito.ru/all?q={encoded}"
            status, body = self._fetch(url)
            if status == 200 and body:
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"avito_search:{username}",
                            confidence=0.4,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))

        # Name search (Cyrillic)
        from translit import transliterate_to_cyrillic as _transliterate_to_cyrillic
        cyrillic = _transliterate_to_cyrillic(target_name)
        for variant in cyrillic[:2]:
            encoded = urllib.parse.quote(variant)
            url = f"https://www.avito.ru/all?q={encoded}"
            status, body = self._fetch(url)
            if status == 200 and body:
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"avito_name_search:{variant}",
                            confidence=0.35,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[variant],
                        ))
        return hits
