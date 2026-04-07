"""UALeakAdapter — Ukrainian leak database scanner."""
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


class UALeakAdapter(ReconAdapter):
    """
    Search Ukrainian leak databases and marketplace archives.

    Sources searched:
      - OLX.ua seller profiles (public phone exposure)
      - Nova Poshta sender/receiver leaks (2022-2024 dumps)
      - Besplatka.ua classifieds
      - Telegram bot aggregators (eye-of-god patterns)

    Strategy: name + city combination → phone cross-reference.
    """

    name = "ua_leak"
    region = "ua"

    # Known UA leak file patterns — searched locally in exports/leaks/ if present
    _LEAK_PATTERNS = [
        "nova_poshta_*.jsonl",
        "olx_sellers_*.jsonl",
        "besplatka_*.jsonl",
        "ukrnet_breach_*.jsonl",
    ]

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Scan local leak dumps if available
        leak_dir = self.leak_dir or (RUNS_ROOT / "leaks")
        if leak_dir.exists():
            hits.extend(self._scan_local_leaks(leak_dir, target_name, known_phones, known_usernames))

        # 2. OLX phone-to-name search (public ads API)
        hits.extend(self._search_olx(target_name, known_phones, known_usernames))

        return hits

    def _scan_local_leaks(
        self, leak_dir: Path, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Scan local JSONL leak files for matching records."""
        hits: list[ReconHit] = []
        name_parts = set(target_name.lower().split())
        known_set = set(known_phones)

        for pattern in self._LEAK_PATTERNS:
            for fpath in leak_dir.glob(pattern):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            if line_no > MAX_JSONL_LINES:  # safety cap
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            # Check if record matches target by name or username
                            record_text = json.dumps(record, ensure_ascii=False).lower()
                            name_match = all(part in record_text for part in name_parts)
                            username_match = any(u.lower() in record_text for u in known_usernames)

                            if not (name_match or username_match):
                                continue

                            # Extract phones from this record
                            phones_found = extract_phones_from_text(record_text)
                            new_phones = [p for p in phones_found if p not in known_set]

                            for phone in new_phones:
                                hits.append(ReconHit(
                                    observable_type="phone",
                                    value=phone,
                                    source_module=self.name,
                                    source_detail=f"local_leak:{fpath.name}:L{line_no}",
                                    confidence=0.6 if name_match else 0.4,
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

    def _search_olx(
        self, target_name: str, known_phones: list[str], known_usernames: list[str]
    ) -> list[ReconHit]:
        """Search OLX.ua for seller profiles matching target."""
        hits: list[ReconHit] = []
        # OLX search by username
        for username in known_usernames:
            encoded = urllib.parse.quote(username)
            url = f"https://www.olx.ua/d/uk/list/q-{encoded}/"
            status, body = self._fetch(url)
            if status == 200 and body:
                # Extract phones from OLX listing pages (strict UA/RU only)
                phones = extract_validated_phones(body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"olx_search:{username}",
                            confidence=0.45,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username],
                        ))
        return hits
