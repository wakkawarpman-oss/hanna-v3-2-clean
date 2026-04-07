"""Search4FacesAdapter — Facial recognition pivot for VK/OK profiles."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit


class Search4FacesAdapter(ReconAdapter):
    """
    Search4Faces — facial recognition pivot for VK/OK profiles.

    Takes a face image URL and searches VK and Odnoklassniki
    for matching faces, returning profile URLs.

    Requires: SEARCH4FACES_API_KEY env var
    """

    name = "search4faces"
    region = "global"

    _API_BASE = "https://search4faces.com/api/search"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []
        api_key = os.environ.get("SEARCH4FACES_API_KEY", "").strip()
        if not api_key:
            return hits

        # Collect face image URLs from known profiles
        image_urls = self._collect_face_images(target_name, known_usernames)

        for img_url in image_urls[:3]:
            hits.extend(self._search_faces(api_key, img_url, "vk", target_name))
            hits.extend(self._search_faces(api_key, img_url, "ok", target_name))
            time.sleep(1)  # rate limiting

        return hits

    def _collect_face_images(self, target_name: str, known_usernames: list[str]) -> list[str]:
        """Collect face image URLs from known profiles."""
        urls: list[str] = []
        for username in known_usernames:
            urls.append(f"https://instagram.com/{urllib.parse.quote(username, safe='')}/")
        return urls

    def _search_faces(
        self, api_key: str, image_url: str, source_db: str, target_name: str
    ) -> list[ReconHit]:
        """Call Search4Faces API to find matching faces."""
        hits: list[ReconHit] = []

        data = {
            "image_url": image_url,
            "source": source_db,
        }
        headers = {"X-Api-Key": api_key}

        status, body = self._post(self._API_BASE, data=data, headers=headers)
        if status != 200 or not body:
            return hits

        try:
            result = json.loads(body)
            faces = result.get("results", result.get("faces", []))
            for face in faces[:10]:
                profile_url = face.get("url", face.get("profile", ""))
                similarity = face.get("similarity", face.get("score", 0.0))
                full_name = face.get("name", face.get("full_name", ""))

                if not profile_url:
                    continue

                name_parts = set(target_name.lower().split())
                name_match = any(p in full_name.lower() for p in name_parts if len(p) > 2) if full_name else False

                conf = min(0.9, similarity) if isinstance(similarity, (int, float)) and similarity > 0 else 0.4
                if name_match:
                    conf = min(1.0, conf + 0.15)

                hits.append(ReconHit(
                    observable_type="url",
                    value=profile_url,
                    source_module=self.name,
                    source_detail=f"face_match:{source_db}:{similarity:.0%}" if isinstance(similarity, float) else f"face_match:{source_db}",
                    confidence=conf,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "source_db": source_db,
                        "similarity": similarity,
                        "name_found": full_name,
                        "name_match": name_match,
                        "image_url_searched": image_url,
                    },
                    cross_refs=[target_name],
                ))
        except (json.JSONDecodeError, TypeError):
            pass

        return hits
