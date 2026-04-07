"""NucleiAdapter — Template-based vulnerability scanning via ProjectDiscovery nuclei."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import resolve_cli_timeout, run_cli
from config import (
    NUCLEI_DEEP_BULK_SIZE,
    NUCLEI_DEEP_CONCURRENCY,
    NUCLEI_DEEP_RATE_LIMIT,
    NUCLEI_DEEP_TARGET_CAP,
    NUCLEI_DEEP_TIMEOUT_MULTIPLIER,
    NUCLEI_PROFILE,
    NUCLEI_QUICK_BULK_SIZE,
    NUCLEI_QUICK_CONCURRENCY,
    NUCLEI_QUICK_RATE_LIMIT,
    NUCLEI_QUICK_TARGET_CAP,
    NUCLEI_QUICK_TIMEOUT_MULTIPLIER,
)

log = logging.getLogger("hanna.recon.nuclei")


class NucleiAdapter(ReconAdapter):
    """
    Nuclei template-based vulnerability scanner.

    Scans target URLs/domains with nuclei's template engine and returns
    infrastructure findings (CVEs, misconfigurations, exposed panels, tech detection).

    Requires: nuclei binary in PATH (or NUCLEI_BIN env var).
    Templates auto-update on first run via `nuclei -update-templates`.
    """

    name = "nuclei"
    region = "global"

    _PROFILE_SEVERITIES = {
        "quick": "medium,high,critical",
        "deep": "low,medium,high,critical",
    }

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # Nuclei needs a URL or domain — extract from target_name or usernames
        targets = self._collect_targets(target_name, known_usernames)
        if not targets:
            return hits

        profile = self._profile_name()
        target_cap = NUCLEI_DEEP_TARGET_CAP if profile == "deep" else NUCLEI_QUICK_TARGET_CAP
        for target in targets[:target_cap]:
            hits.extend(self._run_nuclei(target))

        return hits

    def _collect_targets(self, target_name: str, known_usernames: list[str]) -> list[str]:
        """Extract scannable URL/domain targets."""
        targets: list[str] = []
        for val in [target_name] + known_usernames:
            val = val.strip()
            if not val:
                continue
            if val.startswith("http://") or val.startswith("https://"):
                targets.append(val)
            elif "." in val and not " " in val and not "@" in val:
                targets.append(f"https://{val}")
        return targets

    def _run_nuclei(self, target: str) -> list[ReconHit]:
        """Run nuclei against a single target, parse JSON output."""
        hits: list[ReconHit] = []
        nuclei_bin = os.environ.get("NUCLEI_BIN", "nuclei")
        profile = self._profile_name()
        severity = self._PROFILE_SEVERITIES[profile]
        rate_limit = NUCLEI_DEEP_RATE_LIMIT if profile == "deep" else NUCLEI_QUICK_RATE_LIMIT
        bulk_size = NUCLEI_DEEP_BULK_SIZE if profile == "deep" else NUCLEI_QUICK_BULK_SIZE
        concurrency = NUCLEI_DEEP_CONCURRENCY if profile == "deep" else NUCLEI_QUICK_CONCURRENCY
        timeout_multiplier = NUCLEI_DEEP_TIMEOUT_MULTIPLIER if profile == "deep" else NUCLEI_QUICK_TIMEOUT_MULTIPLIER

        cmd = [
            nuclei_bin,
            "-u", target,
            "-j",             # JSON lines output
            "-silent",
            "-duc",           # disable update checks to avoid startup stalls
            "-severity", severity,
            "-rate-limit", str(rate_limit),
            "-bulk-size", str(bulk_size),
            "-concurrency", str(concurrency),
            "-timeout", str(int(self.timeout)),
            "-no-color",
        ]

        proc = run_cli(
            cmd,
            timeout=resolve_cli_timeout(self.name, self.timeout, timeout_multiplier),
            proxy=self.proxy,
            proxy_cli_flag="-proxy",
        )
        if proc is None:
            log.warning("nuclei execution failed (missing binary, timeout, or runtime error): %s", nuclei_bin)
            return hits

        if proc.returncode == 124:
            log.warning("nuclei scan timed out for target: %s", target)
            return hits

        if not proc.stdout:
            return hits

        for line in proc.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            template_id = obj.get("template-id", obj.get("templateID", ""))
            severity = obj.get("info", {}).get("severity", "unknown")
            matched = obj.get("matched-at", obj.get("matched", target))
            name = obj.get("info", {}).get("name", template_id)

            conf_map = {"critical": 0.95, "high": 0.85, "medium": 0.65, "low": 0.45}
            confidence = conf_map.get(severity, 0.4)

            hits.append(ReconHit(
                observable_type="infrastructure",
                value=f"{severity.upper()}: {name} @ {matched}",
                source_module=self.name,
                source_detail=f"nuclei:{template_id}:{severity}",
                confidence=confidence,
                raw_record=obj,
                timestamp=datetime.now().isoformat(),
                cross_refs=[target],
            ))

        self._record_success()
        return hits

    def _profile_name(self) -> str:
        return "deep" if NUCLEI_PROFILE == "deep" else "quick"
