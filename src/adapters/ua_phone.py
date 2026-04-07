"""UAPhoneAdapter — Reverse phone lookup through UA-specific services."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit

log = logging.getLogger("hanna.recon.ua_phone")


class UAPhoneAdapter(ReconAdapter):
    """
    Reverse phone lookup through UA-specific services.
    Checks GetContact tags (with full AES-encrypted API), Telegram phone→account linking.

    Live methods require env vars:
      - TELEGRAM_BOT_TOKEN     → Bot API phone resolution
      - GETCONTACT_TOKEN       → GetContact API token (from rooted device)
      - GETCONTACT_AES_KEY     → GetContact AES key  (from rooted device)
    If env vars are absent, the adapter falls back to the passive stub.
    """

    name = "ua_phone"
    region = "ua"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._gc_client = None
        token = os.environ.get("GETCONTACT_TOKEN", "").strip()
        aes_key = os.environ.get("GETCONTACT_AES_KEY", "").strip()
        if token and aes_key:
            try:
                from adapters.getcontact_client import GetContactClient
                self._gc_client = GetContactClient(
                    token=token, aes_key=aes_key, timeout=self.timeout
                )
                log.info("GetContact client initialized (token=%s...)", token[:8])
            except Exception as exc:
                log.warning("GetContact client init failed: %s", exc)

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        for phone in known_phones:
            # 1) Live Telegram phone→username resolution
            tg_hits = self._check_telegram_phone_live(phone, target_name)
            hits.extend(tg_hits)

            # 2) GetContact — full encrypted API with tags
            gc_hits = self._check_getcontact_phone(phone, target_name)
            hits.extend(gc_hits)

        return hits

    # ── Telegram live resolution ─────────────────────────────────

    def _check_telegram_phone_live(
        self, phone: str, target_name: str
    ) -> list[ReconHit]:
        """
        Resolve phone→Telegram user via Bot API getChat or contacts.resolvePhone.
        Requires TELEGRAM_BOT_TOKEN env var.  Falls back to passive stub if absent.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            # Passive stub — log for manual follow-up
            return [ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail="telegram_phone_check:pending",
                confidence=0.0,
                timestamp=datetime.now().isoformat(),
                raw_record={"action": "manual_check_required", "service": "telegram", "phone": phone},
            )]

        # Use Telegram Bot API — getChat with phone (unofficial but widespread)
        # The reliable method: create a temporary contact and resolve via getContacts
        # Bot API doesn't expose phone→user directly, so we use the
        # phone_number_privacy workaround: try sending a contact to a
        # helper chat and observing the user_id resolution.
        #
        # Simplified approach: call getChat with the phone-derived user search
        # This is a best-effort check.
        url = f"https://api.telegram.org/bot{token}/getChat"
        try:
            status, body = self._post(url, data={"chat_id": phone})
            if status == 200 and body:
                result = json.loads(body).get("result", {})
                username = result.get("username", "")
                first_name = result.get("first_name", "")
                last_name = result.get("last_name", "")
                full_name = f"{first_name} {last_name}".strip().lower()

                # Check name similarity
                name_parts = set(target_name.lower().split())
                name_match = any(p in full_name for p in name_parts if len(p) > 2)

                conf = 0.7 if name_match else 0.3
                hits = []
                if username:
                    hits.append(ReconHit(
                        observable_type="username",
                        value=username,
                        source_module=self.name,
                        source_detail=f"telegram_bot_api:phone={phone}",
                        confidence=conf,
                        timestamp=datetime.now().isoformat(),
                        raw_record=result,
                        cross_refs=[phone],
                    ))
                if full_name and name_match:
                    hits.append(ReconHit(
                        observable_type="phone",
                        value=phone,
                        source_module=self.name,
                        source_detail=f"telegram_bot_api:name_confirmed",
                        confidence=0.85,
                        timestamp=datetime.now().isoformat(),
                        raw_record=result,
                        cross_refs=[username] if username else [],
                    ))
                return hits if hits else [ReconHit(
                    observable_type="phone",
                    value=phone,
                    source_module=self.name,
                    source_detail="telegram_bot_api:no_match",
                    confidence=0.1,
                    timestamp=datetime.now().isoformat(),
                    raw_record=result,
                )]
        except Exception:
            pass

        return [ReconHit(
            observable_type="phone",
            value=phone,
            source_module=self.name,
            source_detail="telegram_phone_check:api_error",
            confidence=0.0,
            timestamp=datetime.now().isoformat(),
            raw_record={"action": "api_call_failed", "service": "telegram", "phone": phone},
        )]

    # ── GetContact lookup ────────────────────────────────────────

    def _check_getcontact_phone(
        self, phone: str, target_name: str
    ) -> list[ReconHit]:
        """
        Check GetContact for contact-book tags and profile info.
        Uses the full AES-encrypted API via GetContactClient.
        Requires GETCONTACT_TOKEN + GETCONTACT_AES_KEY env vars.
        """
        if not self._gc_client:
            return []

        try:
            info = self._gc_client.get_full_info(phone)
        except Exception as exc:
            log.warning("GetContact lookup failed for %s: %s", phone, exc)
            return []

        if not info:
            return []

        hits: list[ReconHit] = []
        name_parts = set(target_name.lower().split())

        # Profile match (displayName / name)
        display_name = info.get("displayName") or ""
        full_name = info.get("name") or ""
        combined_name = f"{display_name} {full_name}".lower()
        profile_name_match = any(p in combined_name for p in name_parts if len(p) > 2)

        if display_name and display_name != "Not Found":
            conf = 0.80 if profile_name_match else 0.35
            hits.append(ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail=f"getcontact:profile={display_name[:60]}",
                confidence=min(1.0, conf),
                timestamp=datetime.now().isoformat(),
                raw_record={
                    "displayName": display_name,
                    "name": full_name,
                    "country": info.get("country"),
                    "email": info.get("email"),
                    "is_spam": info.get("is_spam", False),
                    "remaining_searches": info.get("remaining_searches"),
                    "name_match": profile_name_match,
                },
                cross_refs=[],
            ))

            # If email found, emit as separate observable
            email = info.get("email")
            if email:
                hits.append(ReconHit(
                    observable_type="email",
                    value=email,
                    source_module=self.name,
                    source_detail="getcontact:profile_email",
                    confidence=min(1.0, 0.75 if profile_name_match else 0.40),
                    timestamp=datetime.now().isoformat(),
                    raw_record={"phone": phone, "displayName": display_name},
                    cross_refs=[phone],
                ))

        # Tags (how others saved this number in their contacts)
        tags = info.get("tags", [])
        for tag in tags[:10]:
            tag_lower = tag.lower()
            tag_name_match = any(p in tag_lower for p in name_parts if len(p) > 2)
            conf = 0.75 if tag_name_match else 0.20
            hits.append(ReconHit(
                observable_type="phone",
                value=phone,
                source_module=self.name,
                source_detail=f"getcontact:tag={tag[:50]}",
                confidence=min(1.0, conf),
                timestamp=datetime.now().isoformat(),
                raw_record={"tag": tag, "phone": phone, "name_match": tag_name_match},
                cross_refs=[],
            ))

        remaining = info.get("remaining_searches")
        if remaining is not None:
            log.info("GetContact remaining searches: %s", remaining)

        return hits
