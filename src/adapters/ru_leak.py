"""RULeakAdapter — Russian leak database scanner."""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from adapters.base import (
    ReconAdapter,
    ReconHit,
    extract_phones_from_text,
    extract_validated_phones,
)
from config import MAX_JSONL_LINES, RUNS_ROOT


class RULeakAdapter(ReconAdapter):
    """
    Search Russian leak databases.

    Sources:
      - VK.com profile data leaks (2019-2023)
      - Yandex Food / Delivery Club delivery leaks
      - SDEK shipping records
      - Mail.ru associated services

    Strategy: nickname search → phone extraction → cross-reference with UA phones.
    """

    name = "ru_leak"
    region = "ru"

    _LEAK_PATTERNS = [
        "vk_dump_*.jsonl",
        "yandex_food_*.jsonl",
        "delivery_club_*.jsonl",
        "sdek_*.jsonl",
        "mailru_*.jsonl",
    ]

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Local leak files
        leak_dir = self.leak_dir or (RUNS_ROOT / "leaks")
        if leak_dir.exists():
            hits.extend(self._scan_local_leaks(leak_dir, target_name, known_phones, known_usernames))

        # 2. VK public profile search
        hits.extend(self._search_vk_public(target_name, known_phones, known_usernames))

        return hits

    def _scan_local_leaks(
        self, leak_dir: Path, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Same logic as UA adapter but for RU leak patterns."""
        hits: list[ReconHit] = []
        name_parts = set(target_name.lower().split())
        known_set = set(known_phones)

        # Also transliterate name for Cyrillic matching
        from translit import transliterate_to_cyrillic as _transliterate_to_cyrillic
        cyrillic_variants = _transliterate_to_cyrillic(target_name)

        for pattern in self._LEAK_PATTERNS:
            for fpath in leak_dir.glob(pattern):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            if line_no > MAX_JSONL_LINES:
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            record_text = json.dumps(record, ensure_ascii=False).lower()

                            # Match: latin name parts OR cyrillic variants OR username
                            name_match = all(part in record_text for part in name_parts)
                            cyrillic_match = any(v.lower() in record_text for v in cyrillic_variants)
                            username_match = any(u.lower() in record_text for u in known_usernames)

                            if not (name_match or cyrillic_match or username_match):
                                continue

                            # Extract new phones
                            phones_found = extract_phones_from_text(record_text)
                            new_phones = [p for p in phones_found if p not in known_set]

                            base_conf = 0.55
                            if name_match and username_match:
                                base_conf = 0.75
                            elif cyrillic_match:
                                base_conf = 0.65

                            for phone in new_phones:
                                hits.append(ReconHit(
                                    observable_type="phone",
                                    value=phone,
                                    source_module=self.name,
                                    source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                    confidence=base_conf,
                                    raw_record=record,
                                    timestamp=datetime.now().isoformat(),
                                    cross_refs=list(known_set),
                                ))

                            # Also extract emails
                            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", record_text)
                            for email in emails:
                                email = email.lower()
                                if "noreply" not in email and "example" not in email:
                                    hits.append(ReconHit(
                                        observable_type="email",
                                        value=email,
                                        source_module=self.name,
                                        source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                        confidence=0.5 if name_match else 0.3,
                                        raw_record=record,
                                        timestamp=datetime.now().isoformat(),
                                    ))
                except (OSError, PermissionError):
                    continue

        return hits

    def _search_vk_public(
        self, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Search VK public people search for matching profiles."""
        hits: list[ReconHit] = []
        for username in known_usernames:
            # VK public page — no API key needed for public profiles
            url = f"https://vk.com/{urllib.parse.quote(username)}"
            status, body = self._fetch(url)
            if status == 200 and body:
                # Check if page actually belongs to target (not a generic 404-like page)
                name_lower = target_name.lower()
                body_lower = body.lower()

                # VK pages contain the name in <title> or og:title
                name_parts = name_lower.split()
                name_found = any(part in body_lower for part in name_parts if len(part) > 3)

                if name_found:
                    # Extract phone numbers shown on public profile (strict)
                    phones = extract_validated_phones(body)
                    known_set = set(known_phones)
                    for phone in phones:
                        if phone not in known_set:
                            hits.append(ReconHit(
                                observable_type="phone",
                                value=phone,
                                source_module=self.name,
                                source_detail=f"vk_profile:{username}",
                                confidence=0.7,
                                timestamp=datetime.now().isoformat(),
                                cross_refs=[username, url],
                            ))

                    # Extract linked contacts (Telegram, Instagram, etc.)
                    tg_matches = re.findall(r"t\.me/([a-zA-Z0-9_]{3,32})", body)
                    for tg in tg_matches:
                        hits.append(ReconHit(
                            observable_type="username",
                            value=tg,
                            source_module=self.name,
                            source_detail=f"vk_profile_link:{username}",
                            confidence=0.5,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))
        return hits
