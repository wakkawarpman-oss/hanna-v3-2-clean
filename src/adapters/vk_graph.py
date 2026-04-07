"""VKGraphAdapter — VK/OK social graph analysis."""
from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit, extract_validated_phones


class VKGraphAdapter(ReconAdapter):
    """
    Analyze VK/OK social graph — friend lists, relatives, wall mentions.

    Strategy:
      1. Fetch public friend list from target's VK profile
      2. Scan friends' walls for target's phone mentions
      3. Check for "alternative contact" in target's info section
    """

    name = "vk_graph"
    region = "ru"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []
        for username in known_usernames:
            # Fetch VK profile page
            url = f"https://vk.com/{urllib.parse.quote(username)}"
            status, body = self._fetch(url)
            if status != 200 or not body:
                continue

            # Extract VK user ID from page source
            uid_match = re.search(r'"rid":\s*(\d+)', body) or re.search(r'data-id="(\d+)"', body)
            if not uid_match:
                continue

            vk_uid = uid_match.group(1)

            # Fetch public friends list (no API key, limited to public profiles)
            friends_url = f"https://vk.com/friends?id={vk_uid}&section=all"
            f_status, f_body = self._fetch(friends_url)
            if f_status != 200 or not f_body:
                continue

            # Extract friend profile URLs
            friend_hrefs = set(re.findall(r'href="/([a-zA-Z0-9_.]+)"', f_body))
            # Cap at 50 to avoid abuse
            friend_hrefs = list(friend_hrefs)[:50]

            name_parts = set(target_name.lower().split())

            # Check each friend's wall for target's phone
            for friend_id in friend_hrefs[:20]:  # limit deep scan
                wall_url = f"https://vk.com/{friend_id}?w=wall"
                w_status, w_body = self._fetch(wall_url)
                if w_status != 200 or not w_body:
                    continue

                # Check if friend's wall mentions target's name
                w_lower = w_body.lower()
                if not any(part in w_lower for part in name_parts if len(part) > 3):
                    continue

                # Extract phones from wall context (strict UA/RU only)
                phones = extract_validated_phones(w_body)
                known_set = set(known_phones)
                for phone in phones:
                    if phone not in known_set:
                        hits.append(ReconHit(
                            observable_type="phone",
                            value=phone,
                            source_module=self.name,
                            source_detail=f"vk_friend_wall:{friend_id}",
                            confidence=0.5,
                            timestamp=datetime.now().isoformat(),
                            cross_refs=[username, friend_id],
                        ))

                time.sleep(0.5)  # rate limiting

        return hits
