"""Reporting service for DiscoveryEngine."""
from __future__ import annotations

import html as html_mod
import json
import re
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config import RUNS_ROOT

TIER_CONFIRMED = "confirmed"
TIER_PROBABLE = "probable"
TIER_UNVERIFIED = "unverified"


class ReportRenderer:
    """Owns dossier rendering and redaction workflows."""

    def __init__(
        self,
        engine: Any,
        *,
        placeholder_domains: Collection[str],
        redaction_modes: Collection[str],
        strip_ansi: Callable[[str], str],
    ):
        self.engine = engine
        self.placeholder_domains = frozenset(placeholder_domains)
        self.redaction_modes = frozenset(redaction_modes)
        self.strip_ansi = strip_ansi

    def get_runs_dir(self) -> Path:
        db_list = self.engine.db.execute("PRAGMA database_list").fetchall()
        for row in db_list:
            db_file = row[2]
            if db_file:
                return Path(db_file).resolve().parent
        return RUNS_ROOT

    @staticmethod
    def get_lane_registry() -> dict[str, str]:
        from registry import MODULE_LANE

        return dict(MODULE_LANE)

    @staticmethod
    def lane_from_source_tool(source_tool: str, lane_registry: dict[str, str]) -> str | None:
        if not source_tool:
            return None
        module_name = source_tool.split(":", 1)[1] if source_tool.startswith("deep_recon:") else source_tool
        return lane_registry.get(module_name)

    def load_latest_deep_recon_report(self) -> dict[str, Any] | None:
        runs_dir = self.get_runs_dir()
        candidates = sorted(runs_dir.glob("deep_recon_*.json"))
        if not candidates:
            return None

        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        payload["_path"] = str(latest)
        return payload

    def build_lane_summary(self, primary) -> dict[str, Any]:
        lane_registry = self.get_lane_registry()
        latest_report = self.load_latest_deep_recon_report()
        summary: dict[str, Any] = {
            "artifact": latest_report,
            "fast": {
                "label": "Fast Lane",
                "modules_run": [],
                "hits": [],
                "errors": [],
                "observables": [],
            },
            "slow": {
                "label": "Slow Lane",
                "modules_run": [],
                "hits": [],
                "errors": [],
                "observables": [],
            },
        }

        if latest_report:
            for module_name in latest_report.get("modules", []):
                lane_name = lane_registry.get(module_name)
                if lane_name in summary:
                    summary[lane_name]["modules_run"].append(module_name)

            for hit in latest_report.get("hits", []):
                lane_name = lane_registry.get(str(hit.get("source", "")))
                if lane_name in summary:
                    summary[lane_name]["hits"].append(hit)

            for error in latest_report.get("errors", []):
                lane_name = lane_registry.get(str(error.get("module", "")))
                if lane_name in summary:
                    summary[lane_name]["errors"].append(error)

        seen_obs: set[tuple[str, str, str]] = set()
        observable_rows = self.engine.db.execute(
            "SELECT obs_type, value, tier, source_tool FROM observables WHERE source_tool LIKE 'deep_recon:%'"
        ).fetchall()
        for row in observable_rows:
            lane_name = self.lane_from_source_tool(str(row[3]), lane_registry)
            if lane_name not in ("fast", "slow"):
                continue
            obs_key = (lane_name, str(row[0]), str(row[1]))
            if obs_key in seen_obs:
                continue
            seen_obs.add(obs_key)
            summary[lane_name]["observables"].append({
                "type": str(row[0]),
                "value": str(row[1]),
                "tier": str(row[2]),
                "source_tool": str(row[3]),
            })

        return summary

    @staticmethod
    def _mask_middle(value: str, keep_start: int = 1, keep_end: int = 1, mask_char: str = "*") -> str:
        if not value:
            return value
        if len(value) <= keep_start + keep_end:
            return mask_char * len(value)
        return value[:keep_start] + (mask_char * (len(value) - keep_start - keep_end)) + value[-keep_end:]

    @classmethod
    def _redact_domain(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        domain = value.strip().lower()
        labels = [label for label in domain.split(".") if label]
        if len(labels) < 2:
            return cls._mask_middle(domain, keep_start=1, keep_end=0)
        masked_labels = [cls._mask_middle(label, keep_start=1, keep_end=0) for label in labels[:-1]]
        masked_labels.append(labels[-1])
        return ".".join(masked_labels)

    @classmethod
    def _redact_phone(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        prefix_len = 4 if value.startswith("+") else 2
        suffix_len = 2 if mode == "shareable" else 0
        return cls._mask_middle(value, keep_start=prefix_len, keep_end=suffix_len)

    @classmethod
    def _redact_email(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        if "@" not in value:
            return cls._mask_middle(value, keep_start=1, keep_end=0)
        local_part, domain = value.split("@", 1)
        masked_local = cls._mask_middle(local_part, keep_start=1, keep_end=0)
        return f"{masked_local}@{cls._redact_domain(domain, mode)}"

    @classmethod
    def _redact_username(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        if mode == "strict":
            return cls._mask_middle(value, keep_start=1, keep_end=0)
        return cls._mask_middle(value, keep_start=2, keep_end=1)

    @classmethod
    def _redact_generic_text(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        parts = re.split(r"(\s+)", value)
        masked: list[str] = []
        for part in parts:
            if not part or part.isspace():
                masked.append(part)
                continue
            masked.append(cls._mask_middle(part, keep_start=1, keep_end=0 if mode == "strict" else 1))
        return "".join(masked)

    @classmethod
    def _redact_url(cls, value: str, mode: str) -> str:
        if mode == "internal":
            return value
        parsed = urlparse(value)
        host = parsed.hostname or parsed.netloc or value
        masked_host = cls._redact_domain(host, mode)
        path = parsed.path.strip("/")
        if not path:
            return f"{parsed.scheme}://{masked_host}" if parsed.scheme else masked_host
        first_segment = path.split("/", 1)[0]
        masked_segment = cls._mask_middle(first_segment, keep_start=1, keep_end=0)
        suffix = "/..." if "/" in path else ""
        if parsed.scheme:
            return f"{parsed.scheme}://{masked_host}/{masked_segment}{suffix}"
        return f"{masked_host}/{masked_segment}{suffix}"

    def redact_value(self, value: str, obs_type: str | None = None, mode: str = "shareable") -> str:
        if mode == "internal" or not value:
            return value
        inferred = obs_type or self.engine._infer_type(value) or "text"
        if inferred == "phone":
            return self._redact_phone(value, mode)
        if inferred == "email":
            return self._redact_email(value, mode)
        if inferred == "domain":
            return self._redact_domain(value, mode)
        if inferred == "url":
            return self._redact_url(value, mode)
        if inferred == "username":
            return self._redact_username(value, mode)
        return self._redact_generic_text(value, mode)

    def render_graph_report(self, output_path: str | Path | None = None, redaction_mode: str = "shareable") -> str:
        """Render a person-centric intelligence dossier as HTML."""
        if redaction_mode not in self.redaction_modes:
            raise ValueError(f"Unsupported redaction_mode: {redaction_mode}")
        stats = self.engine.get_stats()
        pivot_queue = self.engine.get_pivot_queue()
        primary = self.engine.clusters[0] if self.engine.clusters else None
        esc = html_mod.escape

        if primary:
            obs_by_type: dict[str, list[str]] = {}
            for obs in primary.observables:
                obs_by_type.setdefault(obs.obs_type, []).append(obs.value)

            confirmed_obs = [o for o in primary.observables if o.tier == TIER_CONFIRMED]
            probable_obs = [o for o in primary.observables if o.tier == TIER_PROBABLE]
            unverified_obs = [o for o in primary.observables if o.tier == TIER_UNVERIFIED]

            summary_parts = [f"<strong>Primary Identity:</strong> {esc(self.redact_value(primary.label, mode=redaction_mode))}"]
            if "phone" in obs_by_type:
                summary_parts.append(f"<strong>Phone(s):</strong> {', '.join(esc(self.redact_value(phone, 'phone', redaction_mode)) for phone in sorted(set(obs_by_type['phone'])))}")
            if "email" in obs_by_type:
                summary_parts.append(f"<strong>Email(s):</strong> {', '.join(esc(self.redact_value(email, 'email', redaction_mode)) for email in sorted(set(obs_by_type['email'])))}")
            if "username" in obs_by_type:
                summary_parts.append(f"<strong>Username(s):</strong> {', '.join(esc(self.redact_value(username, 'username', redaction_mode)) for username in sorted(set(obs_by_type['username'])))}")
            if "domain" in obs_by_type:
                domains = [domain for domain in sorted(set(obs_by_type["domain"])) if domain.lower() not in self.placeholder_domains]
                if domains:
                    summary_parts.append(f"<strong>Domain(s):</strong> {', '.join(esc(self.redact_value(domain, 'domain', redaction_mode)) for domain in domains)}")
            summary_parts.append(
                f"<strong>Cluster confidence:</strong> {primary.confidence:.0%} "
                f"({len(confirmed_obs)} confirmed, {len(probable_obs)} probable, {len(unverified_obs)} unverified)"
            )
            summary_parts.append(f"<strong>Social profiles found:</strong> {len(primary.profile_urls)}")
            if self.engine._confirmed_imports:
                import_total = sum(item["imported"] for item in self.engine._confirmed_imports)
                import_labels = ", ".join(item["label"] for item in self.engine._confirmed_imports)
                summary_parts.append(f"<strong>Confirmed evidence injected:</strong> {import_total} via {esc(import_labels)}")
        else:
            summary_parts = ["No identity clusters resolved."]
            confirmed_obs = []
            probable_obs = []
            unverified_obs = []

        summary_html = "".join(f"<p>{part}</p>" for part in summary_parts)
        tool_badges = ""
        for tool, tool_stats in sorted(self.engine._tool_stats.items()):
            total = tool_stats["success"] + tool_stats["failed"]
            css_class = "badge-ok" if tool_stats["failed"] == 0 else "badge-warn"
            tool_badges += f"<span class='badge {css_class}'>{esc(tool)}: {tool_stats['success']}/{total} OK, {tool_stats['observables']} obs</span> "

        lane_summary = self.build_lane_summary(primary)
        lane_cards_html = ""
        lane_artifact = lane_summary.get("artifact")
        lane_source_note = ""
        if lane_artifact:
            lane_source_note = (
                f"Latest deep recon artifact: <span class='mono'>{esc(Path(str(lane_artifact['_path'])).name)}</span> "
                f"({esc(str(lane_artifact.get('started', 'n/a')))} → {esc(str(lane_artifact.get('finished', 'n/a')))})"
            )

        for lane_name in ("fast", "slow"):
            lane_data = lane_summary[lane_name]
            modules_run = sorted(set(lane_data["modules_run"]))
            evidence_modules = sorted({
                item["source_tool"].split(":", 1)[1]
                for item in lane_data["observables"]
                if item.get("source_tool", "").startswith("deep_recon:")
            })
            if modules_run:
                module_badges = " ".join(f"<span class='badge badge-lane-module'>{esc(module_name)}</span>" for module_name in modules_run)
            elif evidence_modules:
                module_badges = "<span class='hint'>Historical evidence modules:</span> " + " ".join(
                    f"<span class='badge badge-lane-module'>{esc(module_name)}</span>" for module_name in evidence_modules
                )
            else:
                module_badges = "<span class='hint'>No modules recorded in latest artifact.</span>"

            confirmed_count = sum(1 for obs in lane_data["observables"] if obs["tier"] in (TIER_CONFIRMED, TIER_PROBABLE))
            rejected_count = sum(1 for obs in lane_data["observables"] if obs["tier"] == "rejected")
            dead_end_count = sum(1 for obs in lane_data["observables"] if obs["tier"] not in (TIER_CONFIRMED, TIER_PROBABLE, "rejected"))
            lane_title_meta = (
                "<div class='lane-snr'>"
                f"<span class='lane-snr-badge lane-snr-confirmed' title='Confirmed: corroborated or validated evidence ready for analyst attention.'>{confirmed_count} confirmed</span>"
                f"<span class='lane-snr-badge lane-snr-rejected' title='Rejected: filtered false positives, such as platform artefacts or invalid profile hits.'>{rejected_count} rejected</span>"
                f"<span class='lane-snr-badge lane-snr-dead' title='Dead-end: leads that did not confirm and currently terminate without escalation.'>{dead_end_count} dead-end</span>"
                "</div>"
            )

            if lane_name == "slow" and lane_data["observables"]:
                confirmed_lane_obs = [obs for obs in lane_data["observables"] if obs["tier"] in (TIER_CONFIRMED, TIER_PROBABLE)]
                dead_end_obs = [obs for obs in lane_data["observables"] if obs["tier"] not in (TIER_CONFIRMED, TIER_PROBABLE)]
                confirmed_items = "".join(
                    f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> <code>{esc(self.redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span> <span class='hint'>via {esc(obs['source_tool'])}</span></li>"
                    for obs in confirmed_lane_obs[:8]
                ) or "<li class='hint'>No confirmed slow-lane evidence registered yet.</li>"
                dead_end_items = "".join(
                    f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> <code>{esc(self.redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span> <span class='hint'>via {esc(obs['source_tool'])}</span></li>"
                    for obs in dead_end_obs[:12]
                )
                dead_end_block = ""
                if dead_end_items:
                    dead_end_block = "<details class='lane-dead-ends'><summary>Rejected / Dead Ends (" + str(len(dead_end_obs)) + ")</summary><ul class='lane-muted-list'>" + dead_end_items + "</ul></details>"
                highlights_html = "<div class='lane-evidence-block lane-evidence-confirmed'><strong>Confirmed Evidence:</strong><ul>" + confirmed_items + "</ul></div>" + dead_end_block
            else:
                highlights: list[str] = []
                seen_highlights: set[tuple[str, str]] = set()
                sorted_hits = sorted(lane_data["hits"], key=lambda item: (float(item.get("confidence", 0.0)), str(item.get("value", ""))), reverse=True)
                for hit in sorted_hits:
                    hit_key = (str(hit.get("type", "")), str(hit.get("value", "")))
                    if hit_key in seen_highlights:
                        continue
                    seen_highlights.add(hit_key)
                    confidence = float(hit.get("confidence", 0.0) or 0.0)
                    confidence_label = "pending manual check" if confidence <= 0 else f"{confidence:.0%} confidence"
                    detail = str(hit.get("detail", ""))[:90]
                    highlights.append(
                        f"<li><span class='badge badge-{esc(str(hit.get('type', 'url')))}'>{esc(str(hit.get('type', 'signal')))}</span> <code>{esc(self.redact_value(str(hit.get('value', '')), str(hit.get('type', 'url')), redaction_mode))}</code> <span class='hint'>[{esc(confidence_label)} · {esc(self.redact_value(detail, mode=redaction_mode))}]</span></li>"
                    )
                    if len(highlights) >= 6:
                        break
                if not highlights:
                    sorted_obs = sorted(lane_data["observables"], key=lambda item: (item["tier"], item["type"], item["value"]))
                    for obs in sorted_obs[:6]:
                        highlights.append(
                            f"<li><span class='badge badge-{esc(obs['type'])}'>{esc(obs['type'])}</span> <code>{esc(self.redact_value(obs['value'], obs['type'], redaction_mode))}</code> <span class='tier-badge tier-{esc(obs['tier'])}'>{esc(obs['tier'].upper())}</span></li>"
                        )
                if not highlights:
                    highlights.append("<li class='hint'>No lane-correlated findings registered in this dossier.</li>")
                highlights_html = f"<strong>Highlights:</strong><ul>{''.join(highlights)}</ul>"

            error_html = ""
            if lane_data["errors"]:
                error_items = "".join(
                    f"<li><code>{esc(str(err.get('module', 'unknown')))}</code> <span class='hint'>{esc(str(err.get('error', 'error')))}</span></li>"
                    for err in lane_data["errors"][:5]
                )
                error_html = f"<div class='lane-errors'><strong>Execution faults:</strong><ul>{error_items}</ul></div>"

            lane_cards_html += (
                f"<div class='lane-card lane-{lane_name}'>"
                f"<div class='lane-head'><div><h3>{esc(lane_data['label'])}</h3>{lane_title_meta}<p class='hint'>{'Hot-path pivots, low-noise surface acquisition.' if lane_name == 'fast' else 'Deep infrastructure, archive, and wide-network enumeration.'}</p></div>"
                f"<div class='lane-metrics'><span><strong>{len(modules_run)}</strong> modules</span><span><strong>{len(lane_data['hits'])}</strong> raw hits</span><span><strong>{len(lane_data['observables'])}</strong> dossier observables</span><span><strong>{len(lane_data['errors'])}</strong> faults</span></div></div>"
                f"<div class='lane-modules'><strong>Modules run:</strong> {module_badges}</div><div class='lane-highlights'>{highlights_html}</div>{error_html}</div>"
            )

        graph_nodes_html = ""
        graph_edges_html = ""
        if primary:
            seen_values: set[str] = set()
            for obs in primary.observables:
                if obs.value in seen_values:
                    continue
                seen_values.add(obs.value)
                icon = {"phone": "📱", "email": "📧", "username": "👤", "domain": "🌐", "url": "🔗"}.get(obs.obs_type, "📌")
                tier_css = {"confirmed": "tier-confirmed", "probable": "tier-probable", "unverified": "tier-unverified"}.get(obs.tier, "")
                tier_label = obs.tier.upper()
                graph_nodes_html += f"<div class='gnode gnode-{esc(obs.obs_type)} {tier_css}'>{icon} {esc(self.redact_value(obs.value, obs.obs_type, redaction_mode))} <span class='tier-badge {tier_css}'>{tier_label}</span></div>\n"

            edges = self.engine.db.execute(
                "SELECT obs_a_type, obs_a_value, obs_b_type, obs_b_value, link_reason, confidence FROM entity_links ORDER BY confidence DESC"
            ).fetchall()
            primary_fps = {obs.fingerprint for obs in primary.observables}
            for edge in edges:
                fp_a = f"{edge[0]}:{edge[1]}"
                fp_b = f"{edge[2]}:{edge[3]}"
                if fp_a in primary_fps and fp_b in primary_fps:
                    reason = str(edge[4]).replace("_", " ")
                    graph_edges_html += f"<tr><td>{esc(self.redact_value(edge[1], edge[0], redaction_mode))}</td><td class='edge-reason'>{esc(reason)}</td><td>{esc(self.redact_value(edge[3], edge[2], redaction_mode))}</td><td>{edge[5]:.0%}</td></tr>\n"

        profile_rows_html = ""
        if primary:
            for url in primary.profile_urls[:50]:
                platform = self.engine._platform_from_url(url)
                status_row = self.engine.db.execute("SELECT status FROM profile_urls WHERE url = ?", (url,)).fetchone()
                url_status = status_row[0] if status_row else "unchecked"
                status_badge = {
                    "verified": "<span class='badge badge-ok'>VERIFIED</span>",
                    "soft_match": "<span class='badge badge-warn'>SOFT</span>",
                    "dead": "<span class='badge badge-dead'>DEAD</span>",
                    "unchecked": "<span class='badge'>UNCHECKED</span>",
                }.get(url_status, "")
                redacted_url = self.redact_value(url, "url", redaction_mode)
                if redaction_mode == "internal":
                    profile_cell = f"<a href='{esc(url)}'>{esc(redacted_url)}</a>"
                else:
                    profile_cell = f"<code>{esc(redacted_url)}</code>"
                profile_rows_html += f"<tr><td class='platform'>{esc(platform)}</td><td>{profile_cell}</td><td>{status_badge}</td></tr>\n"

        pivot_rows_html = ""
        for item in pivot_queue[:30]:
            tools = ", ".join(item["suggested_tools"])
            obs_type = item["obs_type"]
            value = item["value"]
            reason = item.get("reason", "")
            tier = item.get("tier", "")
            pivot_rows_html += (
                f"<tr><td><span class='badge badge-{esc(obs_type)}'>{esc(obs_type)}</span></td>"
                f"<td><code>{esc(self.redact_value(value, obs_type, redaction_mode))}</code></td><td>{esc(tools)}</td>"
                f"<td>{esc(self.redact_value(reason, mode=redaction_mode))}</td><td><span class='tier-badge tier-{esc(tier)}'>{esc(tier.upper() if tier else '')}</span></td></tr>\n"
            )

        rejected_rows = self.engine.db.execute("SELECT raw_target, reason, source_file FROM rejected_targets LIMIT 20").fetchall()
        rejected_html = ""
        for row in rejected_rows:
            rejected_html += f"<tr><td><code>{esc(self.redact_value(self.strip_ansi(row[0][:80]), mode=redaction_mode))}</code></td><td>{esc(row[1])}</td><td class='mono'>{esc(Path(row[2]).name)}</td></tr>\n"

        secondary_html = ""
        for cluster in self.engine.clusters[1:]:
            obs_summary = ", ".join(sorted({self.redact_value(obs.value, obs.obs_type, redaction_mode) for obs in cluster.observables}))
            secondary_html += f"<tr><td>{esc(self.redact_value(cluster.label, mode=redaction_mode))}</td><td>{len(cluster.observables)}</td><td>{cluster.confidence:.0%}</td><td class='mono'>{esc(obs_summary[:120])}</td></tr>\n"

        all_obs_rows = self.engine.db.execute(
            "SELECT obs_type, value, source_tool, source_target, depth, tier FROM observables ORDER BY CASE tier WHEN 'confirmed' THEN 0 WHEN 'probable' THEN 1 ELSE 2 END, obs_type, value"
        ).fetchall()
        obs_table_html = ""
        for row in all_obs_rows[:100]:
            tier_value = row[5] if len(row) > 5 else "unverified"
            obs_table_html += (
                f"<tr><td><span class='badge badge-{esc(row[0])}'>{esc(row[0])}</span></td>"
                f"<td><code>{esc(self.redact_value(row[1], row[0], redaction_mode))}</code></td><td>{esc(row[2])}</td>"
                f"<td>{esc(self.redact_value(str(row[3])[:30], mode=redaction_mode))}</td><td>{row[4]}</td>"
                f"<td><span class='tier-badge tier-{esc(tier_value)}'>{esc(tier_value.upper())}</span></td></tr>\n"
            )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        icons = {
            "summary": "📋",
            "anchor": "🎯",
            "link": "🔗",
            "globe": "🌐",
            "pivot": "🔄",
            "chart": "📊",
            "people": "👥",
            "reject": "🚫",
        }

        secondary_section = ""
        if len(self.engine.clusters) > 1:
            secondary_section = (
                "<section class='section'><h2>" + icons["people"] + " Secondary Clusters ("
                + str(len(self.engine.clusters) - 1) + ")</h2><div class='pad'><table><tr><th>Label</th><th>Observables</th><th>Confidence</th><th>Values</th></tr>"
                + secondary_html + "</table></div></section>"
            )

        rejected_section = ""
        if rejected_html:
            rejected_section = (
                "<section class='section'><h2>" + icons["reject"] + " Rejected Targets (" + str(stats["rejected_targets"]) + ")</h2><div class='pad'><p class='hint'>"
                "Filtered by input validation: garbage strings, SHA hashes used as targets, profile-target type mismatches, placeholder domains, high-entropy tokens."
                "</p><table><tr><th>Raw Target</th><th>Reason</th><th>Source</th></tr>" + rejected_html + "</table></div></section>"
            )

        anchor_section = "<p>No identity resolved.</p>"
        if primary:
            anchor_section = (
                "<div class='identity-anchor'><div class='name'>" + esc(self.redact_value(primary.label, mode=redaction_mode))
                + "</div><div class='sub'>Person ID: <code>" + esc(primary.person_id[:12]) + "...</code> Confidence: "
                + f"{primary.confidence:.0%}" + " " + str(len(confirmed_obs)) + " confirmed, " + str(len(probable_obs)) + " probable, " + str(len(unverified_obs)) + " unverified</div></div>"
            )

        page = f"""<!doctype html>
<html lang='uk'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Gonzo Evidence Pack v3.0.2 — {esc(self.redact_value(primary.label, mode=redaction_mode) if primary else 'Unknown')}</title>
<style>
:root {{--bg:#f1f4f3;--card:#fff;--border:#d3dbd6;--accent:#1a6b56;--accent2:#112b45;--text:#171f2b;--muted:#5c6e64;--red:#b84c2e;--green:#2a7d3f;--yellow:#b8860b;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:'Segoe UI','Noto Sans',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.55}}
.wrap{{max-width:1280px;margin:0 auto;padding:24px 20px 60px}}
.hero{{background:linear-gradient(135deg,var(--accent2),var(--accent) 65%,#99622d);color:#fff;border-radius:18px;padding:28px 26px}}
.hero h1{{margin:0;font-size:24px;letter-spacing:.5px}}
.hero-sub{{opacity:.85;font-size:13px;margin:4px 0 0}}
.hero-grid{{display:grid;grid-template-columns:1.4fr .6fr;gap:14px;align-items:start}}
.hero-meta{{text-align:right;font-size:12px;opacity:.8}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:10px;margin-top:16px}}
.card{{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:10px;text-align:center}}
.card .k{{font-size:10px;text-transform:uppercase;opacity:.72}}
.card .v{{font-size:24px;font-weight:800;margin-top:1px}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:14px;margin-top:14px;overflow:hidden}}
.section h2{{margin:0;padding:12px 16px;background:#eaf2ed;border-bottom:1px solid var(--border);font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:var(--accent2)}}
.pad{{padding:14px 16px}}
.exec p{{margin:4px 0;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}}
th{{background:#f4f7f5;font-weight:600;font-size:11px;text-transform:uppercase;color:var(--muted)}}
code{{background:#e8ecea;padding:1px 5px;border-radius:4px;font-size:12px}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all}}
a{{color:var(--accent)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:7px;font-size:11px;font-weight:600;margin:1px 3px 1px 0;background:#e0ede7;color:var(--accent2)}}
.badge-phone{{background:#dde8f7;color:#1a3a6b}}.badge-email{{background:#f0e6fa;color:#5a2d82}}.badge-username{{background:#e6f0e8;color:#1a5a2e}}.badge-domain{{background:#fce6d5;color:#7a3d1a}}.badge-url{{background:#f5f5dc;color:#444}}.badge-ok{{background:#d4edda;color:var(--green)}}.badge-warn{{background:#fff3cd;color:#856404}}.badge-dead{{background:#f8d7da;color:var(--red)}}
.platform{{font-weight:600;color:var(--accent);text-transform:capitalize}}
.edge-reason{{font-style:italic;color:var(--muted)}}
details{{margin-bottom:6px}} summary{{cursor:pointer;font-weight:600;padding:3px 0}}
.hint{{color:var(--muted);font-size:12px}}
.graph-grid{{display:flex;flex-wrap:wrap;gap:8px;padding:8px 0}}
.gnode{{padding:8px 14px;border-radius:10px;font-size:13px;font-weight:500;border:2px solid var(--border);background:#fafcfb}}
.gnode-phone{{border-color:#4a90d9;background:#eaf1fb}}.gnode-email{{border-color:#9b59b6;background:#f4ecf9}}.gnode-username{{border-color:var(--green);background:#e8f5e9}}.gnode-domain{{border-color:#e67e22;background:#fdf2e5}}.gnode-url{{border-color:#95a5a6;background:#f9f9f9}}
.identity-anchor{{text-align:center;padding:16px;margin-bottom:12px}}
.identity-anchor .name{{font-size:22px;font-weight:800;color:var(--accent2)}}
.identity-anchor .sub{{font-size:13px;color:var(--muted)}}
.tier-badge{{display:inline-block;padding:1px 6px;border-radius:5px;font-size:10px;font-weight:700;text-transform:uppercase;margin-left:4px}}
.tier-confirmed{{background:#d4edda;color:#155724;border:1px solid #c3e6cb}}
.tier-probable{{background:#fff3cd;color:#856404;border:1px solid #ffeaa7}}
.tier-unverified{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}}
.tier-rejected{{background:#eceff3;color:#4b5563;border:1px solid #cfd8e3}}
.lane-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.lane-card{{border:1px solid var(--border);border-radius:12px;padding:14px;background:linear-gradient(180deg,#fff, #f8fbf9)}}
.lane-fast{{border-top:5px solid #228b5a}}
.lane-slow{{border-top:5px solid #8c5a2b}}
.lane-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
.lane-head h3{{margin:0;font-size:16px;color:var(--accent2)}}
.lane-snr{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.lane-snr-badge{{display:inline-block;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.25px}}
.lane-snr-confirmed{{background:#dff3e5;color:#1f6a35}}
.lane-snr-rejected{{background:#eceff3;color:#55606c}}
.lane-snr-dead{{background:#f6e6dc;color:#8b4f2a}}
.lane-metrics{{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;font-size:12px;color:var(--muted)}}
.lane-metrics span{{background:#eef3f0;border-radius:999px;padding:4px 8px}}
.lane-modules,.lane-highlights,.lane-errors{{margin-top:10px}}
.lane-highlights ul,.lane-errors ul{{margin:8px 0 0 18px;padding:0}}
.lane-evidence-block{{margin-top:8px;padding:10px 12px;border-radius:10px}}
.lane-evidence-confirmed{{background:#eef8f1;border-left:4px solid var(--green)}}
.lane-evidence-confirmed ul{{margin:8px 0 0 18px;padding:0}}
.lane-dead-ends{{margin-top:10px;border:1px dashed #c8d0d8;border-radius:10px;background:#f5f7f8}}
.lane-dead-ends summary{{padding:10px 12px;color:#5f6b76;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}}
.lane-muted-list{{margin:0;padding:0 12px 12px 30px;opacity:.6;font-size:12px}}
.lane-muted-list li{{margin:6px 0}}
.badge-lane-module{{background:#edf3f7;color:#23405e}}
@media(max-width:980px){{.hero-grid,.cards{{grid-template-columns:1fr}}.cards{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class='wrap'>

<div class='hero'>
  <div class='hero-grid'>
    <div>
      <h1>GONZO EVIDENCE PACK v3.0.2</h1>
      <p class='hero-sub'>Phase 8 Atomic Event-Driven Discovery: verification-first architecture with lane-aware deep recon, fast tactical signal, slow strategic depth, and explicit signal-to-noise control.</p>
    </div>
    <div class='hero-meta'>Generated: {esc(now)}<br>Engine: discovery_engine v3.0.2<br>Clusters: {len(self.engine.clusters)}</div>
  </div>
  <div class='cards'>
    <div class='card'><div class='k'>Sources</div><div class='v'>{stats['total_metadata_files']}</div></div>
    <div class='card'><div class='k'>Confirmed</div><div class='v' style='color:#2a7d3f'>{stats['confirmed_observables']}</div></div>
    <div class='card'><div class='k'>Probable</div><div class='v' style='color:#b8860b'>{stats['probable_observables']}</div></div>
    <div class='card'><div class='k'>Unverified</div><div class='v' style='color:#b84c2e'>{stats['unverified_observables']}</div></div>
    <div class='card'><div class='k'>Rejected</div><div class='v'>{stats['rejected_targets']}</div></div>
    <div class='card'><div class='k'>Profiles</div><div class='v'>{stats['profile_urls']}</div></div>
    <div class='card'><div class='k'>Pivots</div><div class='v'>{stats['pending_pivots']}</div></div>
  </div>
</div>

<section class='section'><h2>{icons['summary']} Executive Summary</h2><div class='pad exec'>
  {summary_html}
  <p style='margin-top:10px'><strong>Source coverage:</strong> {tool_badges}</p>
  <p class='hint'>v2 verification-first resolution across {stats['total_metadata_files']} tool outputs. {stats['rejected_targets']} target(s) filtered (hashes, placeholders, type mismatches).</p>
</div></section>

<section class='section'><h2>🏎️ Fast / Slow Lane Summary</h2><div class='pad'>
  <p class='hint'>Operational split of deep recon outputs into hot-path tactical findings and cold-path strategic expansion.</p>
  <p class='hint'>{lane_source_note or 'No deep recon artifact found in runs/. Lane summary falls back to dossier-linked observables only.'}</p>
  <p class='hint'>Legend: <span class='lane-snr-badge lane-snr-confirmed' title='Confirmed: corroborated or validated evidence ready for analyst attention.'>confirmed</span> <span class='lane-snr-badge lane-snr-rejected' title='Rejected: filtered false positives, such as platform artefacts or invalid profile hits.'>rejected</span> <span class='lane-snr-badge lane-snr-dead' title='Dead-end: leads that did not confirm and currently terminate without escalation.'>dead-end</span></p>
  <div class='lane-grid'>
    {lane_cards_html}
  </div>
</div></section>

<section class='section'><h2>{icons['anchor']} Identity Anchor</h2><div class='pad'>
  {anchor_section}
  <div class='graph-grid'>
    {graph_nodes_html}
  </div>
</div></section>

<section class='section'><h2>{icons['link']} Entity Link Graph</h2><div class='pad'>
  <p class='hint'>Links between observables — only applied when at least one side is confirmed/probable.</p>
  <table><tr><th>Observable A</th><th>Link Reason</th><th>Observable B</th><th>Confidence</th></tr>
  {graph_edges_html or "<tr><td colspan='4'>No links</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{icons['globe']} Social Profiles ({len(primary.profile_urls) if primary else 0})</h2><div class='pad'>
  <p class='hint'>Profile URLs discovered by sherlock/maigret. Status: VERIFIED (HTTP 200 + content), SOFT (HTTP 200, low content), DEAD (4xx/5xx/timeout), UNCHECKED (not yet verified).</p>
  <table><tr><th>Platform</th><th>URL</th><th>Status</th></tr>
  {profile_rows_html or "<tr><td colspan='3'>No profiles found</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{icons['pivot']} Auto-Pivot Queue ({len(pivot_queue)})</h2><div class='pad'>
  <p class='hint'>Observables needing further investigation. Reasons explain WHY each pivot is suggested.</p>
  <table><tr><th>Type</th><th>Value</th><th>Suggested Tools</th><th>Reason</th><th>Tier</th></tr>
  {pivot_rows_html or "<tr><td colspan='5'>No pending pivots</td></tr>"}
  </table>
</div></section>

<section class='section'><h2>{icons['chart']} All Observables ({stats['total_observables']})</h2><div class='pad'>
  <table><tr><th>Type</th><th>Value</th><th>Source Tool</th><th>Target</th><th>Depth</th><th>Tier</th></tr>
  {obs_table_html}
  </table>
</div></section>

{secondary_section}

{rejected_section}

</div>
</body>
</html>"""

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(page, encoding="utf-8")

        return page
