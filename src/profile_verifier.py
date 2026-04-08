"""Profile verification service for DiscoveryEngine."""
from __future__ import annotations

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib
from typing import Any

from config import MAX_BODY_BYTES, VERIFY_WORKERS
from net import proxy_aware_request


class ProfileVerifier:
    """Owns profile URL verification and refresh workflows."""

    def __init__(self, engine: Any, *, false_positive_platforms: Collection[str]):
        self.engine = engine
        self.false_positive_platforms = set(false_positive_platforms)

    def _request(self, *args: Any, **kwargs: Any):
        module = importlib.import_module(self.engine.__class__.__module__)
        request_fn = getattr(module, "proxy_aware_request", proxy_aware_request)
        return request_fn(*args, **kwargs)

    def verify_profiles(self, max_checks: int = 50, timeout: float = 5.0, proxy: str | None = None):
        """HTTP HEAD check for profile URLs. Marks verified/dead/soft_match."""
        rows = self.engine.db.execute(
            "SELECT id, url, username FROM profile_urls WHERE status = 'unchecked' LIMIT ?",
            (max_checks,),
        ).fetchall()
        if not rows:
            return

        def _check_url(row):
            url_id, url, _username = row[0], row[1], row[2]
            try:
                status_code, headers, _body = self._request(
                    url,
                    method="HEAD",
                    timeout=timeout,
                    proxy=proxy,
                )
                content_length = int(headers.get("Content-Length", "0") or "0")

                platform = self.engine._platform_from_url(url)
                if platform in self.false_positive_platforms:
                    return (url_id, "soft_match")
                if status_code == 200 and content_length > 500:
                    return (url_id, "verified")
                if status_code == 200:
                    return (url_id, "soft_match")
                return (url_id, "dead")
            except Exception:
                return (url_id, "dead")

        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as executor:
            futures = {executor.submit(_check_url, row): row for row in rows}
            for future in as_completed(futures):
                url_id, status = future.result()
                ttl_hours = 24 if status in ("verified", "dead") else 12
                self.engine.db.execute(
                    """UPDATE profile_urls
                       SET status = ?, checked_at = datetime('now'),
                           last_checked_at = datetime('now'),
                           valid_until = datetime('now', '+' || ? || ' hours')
                       WHERE id = ?""",
                    (status, ttl_hours, url_id),
                )
        self.engine.db.commit()

    def reverify_expired(self, max_checks: int = 50, timeout: float = 5.0, proxy: str | None = None) -> dict[str, int]:
        """Re-verify profile URLs whose TTL has expired."""
        rows = self.engine.db.execute(
            """SELECT id, url, username, status FROM profile_urls
               WHERE valid_until IS NOT NULL
                 AND valid_until < datetime('now')
                 AND status IN ('verified', 'dead', 'soft_match')
               LIMIT ?""",
            (max_checks,),
        ).fetchall()

        if not rows:
            return {"rechecked": 0, "upgraded": 0, "downgraded": 0, "unchanged": 0}

        counts = {"rechecked": 0, "upgraded": 0, "downgraded": 0, "unchanged": 0}

        def _recheck(row):
            url_id, url, _user, old_status = row[0], row[1], row[2], row[3]
            try:
                status_code, headers, _body = self._request(
                    url,
                    method="HEAD",
                    timeout=timeout,
                    proxy=proxy,
                )
                content_length = int(headers.get("Content-Length", "0") or "0")

                platform = self.engine._platform_from_url(url)
                if platform in self.false_positive_platforms:
                    new_status = "soft_match"
                elif status_code == 200 and content_length > 500:
                    new_status = "verified"
                elif status_code == 200:
                    new_status = "soft_match"
                else:
                    new_status = "dead"
                return (url_id, old_status, new_status)
            except Exception:
                return (url_id, old_status, "dead")

        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as executor:
            futures = {executor.submit(_recheck, row): row for row in rows}
            for future in as_completed(futures):
                url_id, old_status, new_status = future.result()
                counts["rechecked"] += 1
                if new_status != old_status:
                    if new_status == "verified" and old_status == "dead":
                        counts["upgraded"] += 1
                    elif new_status == "dead" and old_status in ("verified", "soft_match"):
                        counts["downgraded"] += 1
                    else:
                        counts["unchanged"] += 1
                else:
                    counts["unchanged"] += 1
                ttl_hours = 24 if new_status in ("verified", "dead") else 12
                self.engine.db.execute(
                    """UPDATE profile_urls
                       SET status = ?, checked_at = datetime('now'),
                           last_checked_at = datetime('now'),
                           valid_until = datetime('now', '+' || ? || ' hours')
                       WHERE id = ?""",
                    (new_status, ttl_hours, url_id),
                )
        self.engine.db.commit()
        return counts

    def get_profile_stats(self) -> dict[str, int]:
        """Profile URL counts by verification status."""
        result = {}
        for row in self.engine.db.execute("SELECT status, COUNT(*) FROM profile_urls GROUP BY status"):
            result[row[0]] = row[1]
        return result

    def verify_content(self, max_checks: int = 100, timeout: float = 8.0, proxy: str | None = None) -> dict[str, int]:
        """GET soft-match URLs and upgrade/kill them based on body evidence."""
        rows = self.engine.db.execute(
            "SELECT id, url, username FROM profile_urls WHERE status = 'soft_match' LIMIT ?",
            (max_checks,),
        ).fetchall()
        if not rows:
            return {"upgraded": 0, "killed": 0, "unchanged": 0, "errors": 0, "skipped_blacklisted": 0}

        name_tokens: set[str] = set()
        for obs in self.engine._all_observables:
            if obs.obs_type == "username" and obs.tier == "confirmed":
                name_tokens.add(obs.value.lower())
                for part in obs.value.lower().split():
                    if len(part) >= 3:
                        name_tokens.add(part)
            if obs.obs_type == "phone":
                name_tokens.add(obs.value)
        for cluster in self.engine.clusters:
            for part in cluster.label.lower().split():
                if len(part) >= 3:
                    name_tokens.add(part)

        not_found_patterns = [
            "not found", "no results", "404", "page not found",
            "user not found", "пользователь не найден",
            "не найдено", "нет результатов", "сторінку не знайдено",
            "hasn't posted", "no posts", "no activity",
            "this user doesn't exist", "could not be found",
            "no matches", "ничего не найдено",
        ]
        counts = {"upgraded": 0, "killed": 0, "unchanged": 0, "errors": 0, "skipped_blacklisted": 0}

        def _check_content(row):
            url_id, url, _username = row[0], row[1], row[2]
            platform = self.engine._platform_from_url(url)
            if platform in self.false_positive_platforms:
                return (url_id, "skip_blacklisted")
            try:
                status_code, _headers, body = self._request(
                    url,
                    method="GET",
                    timeout=timeout,
                    proxy=proxy,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "uk,en;q=0.5",
                    },
                    max_body_bytes=MAX_BODY_BYTES,
                )
                if status_code >= 400 or status_code == 0:
                    return (url_id, "dead")

                body_lower = body.lower()
                for marker in not_found_patterns:
                    if marker in body_lower:
                        return (url_id, "dead")

                name_hits = sum(1 for token in name_tokens if token in body_lower)
                if name_hits >= 2:
                    return (url_id, "verified")
                return (url_id, "soft_match")
            except Exception:
                return (url_id, "error")

        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as executor:
            futures = {executor.submit(_check_content, row): row for row in rows}
            for future in as_completed(futures):
                url_id, result = future.result()
                if result == "skip_blacklisted":
                    counts["skipped_blacklisted"] += 1
                elif result == "error":
                    counts["errors"] += 1
                elif result == "verified":
                    counts["upgraded"] += 1
                    self.engine.db.execute(
                        "UPDATE profile_urls SET status = 'verified', content_match = 1, checked_at = datetime('now') WHERE id = ?",
                        (url_id,),
                    )
                elif result == "dead":
                    counts["killed"] += 1
                    self.engine.db.execute(
                        "UPDATE profile_urls SET status = 'dead', checked_at = datetime('now') WHERE id = ?",
                        (url_id,),
                    )
                else:
                    counts["unchanged"] += 1

        self.engine.db.commit()
        return counts
