#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ANALYST_ID = "legacy-bridge"
DEFAULT_API_TOKEN = os.getenv("OSINT_API_TOKEN", "legacy-bridge-local-dev-token")

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def api_request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, api_token: str = DEFAULT_API_TOKEN) -> tuple[int, Any]:
    body = None
    headers = {"Authorization": f"Bearer {api_token}"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "legacy"


def canonical_lookup_value(value: str) -> str:
    return " ".join(strip_ansi(value).strip().split()).lower()


def normalize_target_value(profile: str, target: str) -> str:
    cleaned = strip_ansi(target).strip()
    if profile in {"domain", "dnsenum", "whatweb"}:
        match = re.search(r"Ignored\s+invalid\s+OSINT_DOMAIN\s+value:\s*(.+)$", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
    return cleaned


def tool_name_for_meta(meta: dict[str, Any]) -> str:
    label = strip_ansi(str(meta.get("label") or "")).strip()
    match = re.match(r"dossier_[^_]+_([^_]+)_", label)
    if match:
        return match.group(1)

    profile = str(meta.get("profile") or "").strip().lower()
    fallback = {
        "phone": "phoneinfoga",
        "username": "username",
        "domain": "domain",
        "dnsenum": "dnsenum",
        "whatweb": "whatweb",
        "email": "email",
        "ip": "ip",
    }
    return fallback.get(profile, profile or "legacy")


def supporting_evidence_ids(claim: dict[str, Any], evidence_ids_by_target: dict[str, list[str]]) -> list[str]:
    matches: list[str] = []
    seen_ids: set[str] = set()
    for entity in claim.get("entities", []):
        entity_value = str(entity.get("entity_value") or "")
        lookup = canonical_lookup_value(entity_value)
        for evidence_id in evidence_ids_by_target.get(lookup, []):
            if evidence_id in seen_ids:
                continue
            seen_ids.add(evidence_id)
            matches.append(evidence_id)
    return matches


def parse_phone_log(log_text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "categories": {},
        "urls": [],
        "top_findings": [],
    }
    current_group = None
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":") and not line.startswith("URL:"):
            current_group = line[:-1]
            parsed["categories"].setdefault(current_group, [])
            continue
        if line.startswith("URL:"):
            url = line.split("URL:", 1)[1].strip()
            parsed["urls"].append(url)
            if current_group:
                parsed["categories"].setdefault(current_group, []).append(url)
            continue
        match = re.match(r"^(Raw local|Local|E164|International|Country):\s*(.+)$", line)
        if match:
            key = match.group(1).lower().replace(" ", "_")
            parsed[key] = match.group(2).strip()
            parsed["top_findings"].append(line)
            continue
        if line.startswith("Results for "):
            parsed["top_findings"].append(line)
            continue
    return parsed


def decode_search_pivot(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
    return urllib.parse.unquote_plus(query).strip() or url


def profile_display_name(profile: str) -> str:
    names = {
        "phone": "Phone Intelligence",
        "email": "Email Intelligence",
        "username": "Username Intelligence",
        "domain": "Domain Intelligence",
        "dnsenum": "DNS Enumeration",
        "whatweb": "Web Fingerprint",
        "ip": "IP Intelligence",
    }
    return names.get(profile, profile.replace("_", " ").title())


def infer_entity_type(profile: str, target: str) -> str:
    if profile in {"phone"}:
        return "observable"
    if profile in {"email"}:
        return "identity"
    if profile in {"username"}:
        return "identity"
    if profile in {"domain", "dnsenum", "whatweb"}:
        return "infrastructure"
    if profile == "ip":
        return "infrastructure"
    if "@" in target:
        return "identity"
    if target.startswith("+") or target[:1].isdigit():
        return "observable"
    return "observable"


def ensure_graph(base_url: str, target_label: str, api_token: str) -> str:
    input_node = str(uuid.uuid4())
    processor_node = str(uuid.uuid4())
    status, payload = api_request(
        base_url,
        "POST",
        "/api/v1/graphs",
        {
            "name": f"legacy-phone-dossier-{slug(target_label)}",
            "analyst_id": ANALYST_ID,
            "version": "1",
            "nodes": [
                {
                    "id": input_node,
                    "name": "Legacy Phone Seed",
                    "node_type": "input",
                    "subtype": "phone",
                    "adapter_name": None,
                    "position": {"x": 120, "y": 80},
                    "config": {},
                },
                {
                    "id": processor_node,
                    "name": "PhoneInfoga Legacy Import",
                    "node_type": "processor",
                    "subtype": "phoneinfoga",
                    "adapter_name": "phoneinfoga",
                    "position": {"x": 420, "y": 80},
                    "config": {"source": "legacy-export-bridge"},
                },
            ],
            "edges": [
                {
                    "source_node_id": input_node,
                    "source_port_id": "out",
                    "target_node_id": processor_node,
                    "target_port_id": "in",
                    "observable_type": "phone",
                    "contract_name": "phone->phoneinfoga",
                }
            ],
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"graph creation failed: {payload}")
    return str(payload["graph_id"])


def create_run(base_url: str, graph_id: str, phone: str, api_token: str) -> str:
    status, payload = api_request(
        base_url,
        "POST",
        "/api/v1/runs",
        {
            "graph_id": graph_id,
            "project_id": "legacy-phone-dossier",
            "analyst_id": ANALYST_ID,
            "seeds": [{"observable_type": "phone", "value": phone}],
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"run creation failed: {payload}")
    return str(payload["run_id"])


def post_event(base_url: str, run_id: str, node_id: str, api_token: str, message: str) -> None:
    status, payload = api_request(
        base_url,
        "POST",
        f"/api/v1/runs/{run_id}/events",
        {
            "node_id": node_id,
            "status": "succeeded",
            "message": message,
            "progress_percent": 100,
            "payload": {"source": "legacy-export-bridge"},
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"event creation failed: {payload}")


def intake_evidence(base_url: str, run_id: str, node_id: str, meta: dict[str, Any], log_text: str, api_token: str) -> str:
    status, payload = api_request(
        base_url,
        "POST",
        "/api/v1/evidence/intake",
        {
            "run_id": run_id,
            "node_id": node_id,
            "kind": "execution_log",
            "uri": meta["log_file"],
            "source_uri": meta["log_file"],
            "mime_type": "text/plain",
            "content": log_text,
            "tool_name": tool_name_for_meta(meta),
            "tool_version": "legacy",
            "actor_id": ANALYST_ID,
            "actor_type": "adapter",
            "metadata": {
                "legacy_label": meta.get("label"),
                "legacy_timestamp": meta.get("timestamp"),
                "legacy_profile": meta.get("profile"),
            },
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"evidence intake failed: {payload}")
    return str(payload["artifact_id"])


def create_claim(base_url: str, run_id: str, statement: str, entities: list[dict[str, Any]], claim_value: dict[str, Any], metadata: dict[str, Any], api_token: str) -> str:
    status, payload = api_request(
        base_url,
        "POST",
        "/api/v1/claims",
        {
            "run_id": run_id,
            "claim_type": "assertion",
            "statement": statement,
            "entities": entities,
            "claim_value": claim_value,
            "status": "active",
            "lifecycle_state": "proposed",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "trust_tier": "medium",
            "metadata": metadata,
            "actor_id": ANALYST_ID,
            "actor_type": "adapter",
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"claim creation failed: {payload}")
    return str(payload["claim_id"])


def attach_evidence(base_url: str, claim_id: str, evidence_id: str, api_token: str, confidence: float = 0.72) -> None:
    status, payload = api_request(
        base_url,
        "POST",
        f"/api/v1/claims/{claim_id}/evidence",
        {
            "evidence_id": evidence_id,
            "confidence": confidence,
            "extraction_method": "metadata",
            "actor_id": ANALYST_ID,
            "actor_type": "adapter",
        },
        api_token=api_token,
    )
    if status != 201:
        raise RuntimeError(f"attach evidence failed: {payload}")


def assess_claim(base_url: str, claim_id: str, api_token: str) -> None:
    status, payload = api_request(
        base_url,
        "POST",
        f"/api/v1/claims/{claim_id}/assess?actor_id={ANALYST_ID}&actor_type=adapter",
        api_token=api_token,
    )
    if status != 200:
        raise RuntimeError(f"claim assess failed: {payload}")


def fetch_json(base_url: str, path: str, api_token: str) -> Any:
    status, payload = api_request(base_url, "GET", path, api_token=api_token)
    if status != 200:
        raise RuntimeError(f"GET {path} failed: {payload}")
    return payload


def render_html(session_id: str, metas: list[dict[str, Any]], parsed: dict[str, Any], dossier: dict[str, Any], timeline: dict[str, Any], contradictions: dict[str, Any]) -> str:
    meta = metas[0] if metas else {}
    entities = dossier.get("entities", [])
    relationships = dossier.get("relationships", [])
    claims = dossier.get("claims", [])
    timeline_items = timeline.get("items", [])
    contradiction_items = contradictions.get("items", [])

    # ── Build executive summary ──
    unique_targets: dict[str, set[str]] = {}
    profile_stats: dict[str, dict[str, int]] = {}
    for m in metas:
        profile = str(m.get("profile") or "unknown")
        target = strip_ansi(str(m.get("target") or ""))
        status = str(m.get("status") or "unknown")
        unique_targets.setdefault(profile, set()).add(target)
        stats = profile_stats.setdefault(profile, {"success": 0, "failed": 0})
        if status == "success":
            stats["success"] += 1
        else:
            stats["failed"] += 1

    phones = sorted(unique_targets.get("phone", set()))
    usernames = sorted(unique_targets.get("username", set()))
    domains = sorted(unique_targets.get("domain", set()) | unique_targets.get("whatweb", set()) | unique_targets.get("dnsenum", set()))

    summary_lines: list[str] = []
    if phones:
        summary_lines.append(f"<strong>Phone numbers investigated:</strong> {', '.join(html.escape(p) for p in phones)}")
    if usernames:
        summary_lines.append(f"<strong>Identities / usernames:</strong> {', '.join(html.escape(u) for u in usernames)}")
    if domains:
        summary_lines.append(f"<strong>Web infrastructure:</strong> {', '.join(html.escape(d) for d in domains)}")
    if phones and usernames:
        summary_lines.append(f"Co-occurrence link: phone(s) and username(s) were collected in the same OSINT session, suggesting they belong to the same individual.")
    if usernames and domains:
        summary_lines.append(f"Identity-to-infrastructure link: the website/domain results are likely associated with the username target(s).")
    if parsed.get("country"):
        summary_lines.append(f"<strong>Phone country:</strong> {html.escape(parsed['country'])}")
    if parsed.get("e164"):
        summary_lines.append(f"<strong>E.164 format:</strong> <code>{html.escape(parsed['e164'])}</code>")

    # Source coverage summary
    coverage_lines: list[str] = []
    for profile, stats in sorted(profile_stats.items()):
        total = stats["success"] + stats["failed"]
        coverage_lines.append(f"<span class='badge badge-{profile}'>{html.escape(profile)}: {stats['success']}/{total} OK</span>")

    # ── Separate link claims from collection claims ──
    link_claims: list[dict[str, Any]] = []
    intel_claims: list[dict[str, Any]] = []
    collection_claims: list[dict[str, Any]] = []
    for c in claims:
        stmt = strip_ansi(c.get("statement") or "")
        if "collected legacy evidence" in stmt:
            collection_claims.append(c)
        elif any(kw in stmt for kw in ("associated with", "is linked to", "Phone numbers")):
            link_claims.append(c)
        else:
            intel_claims.append(c)

    # ── Group entities by type ──
    entities_by_type: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        etype = e.get("entity_type") or "unknown"
        entities_by_type.setdefault(etype, []).append(e)

    entity_type_labels = {"observable": "Observables (phones, IDs)", "identity": "Identities (persons, usernames)", "infrastructure": "Infrastructure (domains, websites)", "location": "Locations"}

    entity_sections_html = ""
    for etype in ("observable", "identity", "infrastructure", "location"):
        group = entities_by_type.get(etype, [])
        if not group:
            continue
        row_parts = []
        for item in group:
            disp = html.escape(strip_ansi(item.get('display_name') or item.get('canonical_value') or ''))
            conf = item.get('confidence_score', 0)
            tier = item.get('trust_tier') or 'unknown'
            tier_display = html.escape(item.get('trust_tier') or 'n/a')
            row_parts.append(f"<tr><td>{disp}</td><td>{conf:.2f}</td><td><span class='trust-{html.escape(tier)}'>{tier_display}</span></td></tr>")
        rows = "".join(row_parts)
        label = entity_type_labels.get(etype, etype.title())
        entity_sections_html += f"<h3 class='etype-header'>{html.escape(label)} ({len(group)})</h3><table><tr><th>Value</th><th>Confidence</th><th>Trust</th></tr>{rows}</table>"
    if not entity_sections_html:
        entity_sections_html = "<p>No entities detected.</p>"

    # ── Relationship rows ──
    relationship_rows = "".join(
        f"<tr><td>{html.escape(strip_ansi(item.get('source_display_name') or item.get('source_entity_id') or ''))}</td><td class='rel-type'>{html.escape(item.get('relationship_type') or '')}</td><td>{html.escape(strip_ansi(item.get('target_display_name') or item.get('target_entity_id') or ''))}</td><td>{item.get('confidence_score', 0):.2f}</td></tr>"
        for item in relationships
    ) or "<tr><td colspan='4'>No relationships</td></tr>"

    # ── Link claims rows ──
    link_row_parts = []
    for item in link_claims:
        stmt = html.escape(strip_ansi(item.get('statement') or ''))
        conf = item.get('confidence_score', 0)
        st = item.get('status') or 'unknown'
        link_row_parts.append(f"<tr><td>{stmt}</td><td>{conf:.2f}</td><td><span class='status-{html.escape(st)}'>{html.escape(st)}</span></td></tr>")
    link_rows = "".join(link_row_parts) or "<tr><td colspan='3'>No cross-entity links</td></tr>"

    # ── Intel claims (non-generic, non-link) ──
    intel_rows = "".join(
        f"<tr><td>{html.escape(strip_ansi(item.get('statement') or ''))}</td><td>{html.escape(item.get('status') or '')}</td><td>{item.get('confidence_score', 0):.2f}</td></tr>"
        for item in intel_claims
    ) or "<tr><td colspan='3'>No intelligence claims</td></tr>"

    # ── Timeline ──
    timeline_rows = "".join(
        f"<tr><td class='mono'>{html.escape(item.get('timeline_time') or '')[:19]}</td><td>{html.escape(strip_ansi(item.get('statement') or ''))}</td><td>{item.get('confidence_score', 0):.2f}</td></tr>"
        for item in timeline_items
    ) or "<tr><td colspan='3'>No timeline items</td></tr>"

    # ── Contradictions ──
    contradiction_rows = "".join(
        f"<tr><td>{html.escape(strip_ansi(item.get('claim_statement') or ''))}</td><td>{html.escape(strip_ansi(item.get('conflicting_claim_statement') or ''))}</td><td>{html.escape(item.get('conflict_type') or '')}</td></tr>"
        for item in contradiction_items
    ) or "<tr><td colspan='3'>No contradictions detected</td></tr>"

    # ── Search pivots ──
    url_groups = []
    for group_name, urls in parsed.get("categories", {}).items():
        if not urls:
            continue
        items = ""
        for url in urls[:12]:
            query_text = decode_search_pivot(url)
            if "google.com/search" in url:
                items += f"<li><strong>Pivot</strong>: <span class='mono'>{html.escape(query_text)}</span> <span class='hint'>(search pivot, not evidence)</span></li>"
            else:
                items += f"<li><a href='{html.escape(url)}'>{html.escape(url)}</a></li>"
        url_groups.append(f"<details><summary>{html.escape(group_name)} ({len(urls)})</summary><ul>{items}</ul></details>")
    url_sections = "".join(url_groups) or "<p>No URL groups parsed.</p>"

    # ── Findings ──
    finding_items = "".join(f"<li>{html.escape(item)}</li>" for item in parsed.get("top_findings", [])[:10]) or "<li>No parsed findings</li>"

    # ── Collection log (collapsed) ──
    collection_summary_rows = "".join(
        f"<tr><td>{html.escape(strip_ansi(item.get('statement') or ''))}</td><td>{html.escape(item.get('status') or '')}</td></tr>"
        for item in collection_claims
    )

    return f"""<!doctype html>
<html lang='uk'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>OSINT Dossier — {html.escape(session_id)}</title>
  <style>
    :root {{ --bg: #f3f5f4; --card: #fff; --border: #d6ddd8; --accent: #1f6d5b; --accent2: #112b45; --text: #17212b; --muted: #5c6e64; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Segoe UI', 'Noto Sans', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.55; }}
    .wrap {{ max-width: 1300px; margin: 0 auto; padding: 24px 20px 60px; }}
    .hero {{ background: linear-gradient(135deg, var(--accent2), var(--accent) 70%, #99622d); color: #fff; border-radius: 18px; padding: 28px 24px; }}
    .hero h1 {{ margin: 0; font-size: 26px; letter-spacing: .5px; }}
    .hero-sub {{ opacity: .85; margin: 6px 0 0; font-size: 14px; }}
    .hero-meta {{ text-align: right; font-size: 13px; opacity: .85; }}
    .hero-grid {{ display: grid; grid-template-columns: 1.4fr .6fr; gap: 18px; align-items: start; }}
    .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 18px; }}
    .card {{ background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.18); border-radius: 12px; padding: 12px; text-align: center; }}
    .card .k {{ font-size: 11px; text-transform: uppercase; opacity: .75; }}
    .card .v {{ font-size: 28px; font-weight: 800; margin-top: 2px; }}
    .section {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; margin-top: 16px; overflow: hidden; }}
    .section h2 {{ margin: 0; padding: 13px 16px; background: #ecf3ef; border-bottom: 1px solid var(--border); font-size: 14px; text-transform: uppercase; letter-spacing: .4px; color: var(--accent2); }}
    .pad {{ padding: 16px; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .tri {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ background: #f4f7f5; font-weight: 600; font-size: 12px; text-transform: uppercase; color: var(--muted); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; }}
    code {{ background: #e8ecea; padding: 2px 5px; border-radius: 4px; font-size: 12px; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin-bottom: 4px; }}
    details {{ margin-bottom: 8px; }}
    summary {{ cursor: pointer; font-weight: 600; padding: 4px 0; }}
    pre {{ white-space: pre-wrap; background: #161b18; color: #d5e1da; padding: 14px; border-radius: 10px; overflow: auto; font-size: 12px; }}
    a {{ color: var(--accent); }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 8px; font-size: 12px; font-weight: 600; margin: 2px 4px 2px 0; background: #e0ede7; color: var(--accent2); }}
    .badge-phone {{ background: #dde8f7; }}
    .badge-username {{ background: #f0e6fa; }}
    .badge-domain, .badge-whatweb, .badge-dnsenum {{ background: #fce6d5; }}
    .exec-summary {{ font-size: 14px; line-height: 1.65; }}
    .exec-summary p {{ margin: 6px 0; }}
    .hint {{ color: var(--muted); font-size: 12px; }}
    .etype-header {{ margin: 18px 0 6px; font-size: 13px; text-transform: uppercase; color: var(--accent); border-bottom: 2px solid var(--accent); padding-bottom: 4px; }}
    .etype-header:first-child {{ margin-top: 0; }}
    .rel-type {{ font-weight: 600; color: var(--accent); }}
    .status-confirmed {{ color: #2a7d3f; }}
    .status-assessed {{ color: #1f6d5b; }}
    .status-pending {{ color: #b8860b; }}
    .trust-high {{ color: #2a7d3f; font-weight: 600; }}
    .trust-medium {{ color: #b8860b; font-weight: 600; }}
    .trust-low {{ color: #b84c2e; font-weight: 600; }}
    .kv {{ display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 14px; }}
    .kv dt {{ font-weight: 600; color: var(--muted); }}
    .kv dd {{ margin: 0; }}
    @media (max-width: 980px) {{ .hero-grid, .cards, .split, .tri {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='hero'>
      <div class='hero-grid'>
        <div>
          <h1>OSINT INTELLIGENCE DOSSIER</h1>
          <p class='hero-sub'>Multi-source intelligence report — legacy collection data fused through claim/entity pipeline with cross-entity link analysis.</p>
        </div>
        <div class='hero-meta'>
          Generated: {html.escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}<br>
          Session: {html.escape(session_id)}<br>
          Run: <span class='mono'>{html.escape(dossier.get('run_id', '')[:12])}</span>
        </div>
      </div>
      <div class='cards'>
        <div class='card'><div class='k'>Sources</div><div class='v'>{len(metas)}</div></div>
        <div class='card'><div class='k'>Entities</div><div class='v'>{len(entities)}</div></div>
        <div class='card'><div class='k'>Links</div><div class='v'>{len(link_claims) + len(relationships)}</div></div>
        <div class='card'><div class='k'>Intel Claims</div><div class='v'>{len(intel_claims)}</div></div>
        <div class='card'><div class='k'>Contradictions</div><div class='v'>{len(contradiction_items)}</div></div>
      </div>
    </div>

    <section class='section'><h2>📋 Executive Summary / Аналітичне зведення</h2><div class='pad exec-summary'>
      {"".join(f"<p>{line}</p>" for line in summary_lines)}
      <p style='margin-top:12px;'><strong>Source coverage:</strong> {"  ".join(coverage_lines)}</p>
      <p class='hint'>This report was auto-generated from {len(metas)} legacy collection logs across {len(profile_stats)} tool profiles. Confidence scores reflect pipeline-assessed reliability. Cross-entity links are inferred from session co-occurrence.</p>
    </div></section>

    <section class='section'><h2>🔗 Cross-entity Link Analysis</h2><div class='pad'>
      <p class='hint' style='margin:0 0 10px;'>These claims connect different target types (phone → identity → infrastructure) based on co-occurrence in the same OSINT collection session.</p>
      <table><tr><th>Link Statement</th><th>Confidence</th><th>Status</th></tr>{link_rows}</table>
    </div></section>

    <section class='section'><h2>🎯 Entity Inventory</h2><div class='pad'>
      {entity_sections_html}
    </div></section>

    <section class='section'><h2>↔ Semantic Relationships</h2><div class='pad'>
      <table><tr><th>Source</th><th>Relation</th><th>Target</th><th>Confidence</th></tr>{relationship_rows}</table>
    </div></section>

    <section class='section'><h2>🔍 Intelligence Claims</h2><div class='pad'>
      <p class='hint' style='margin:0 0 10px;'>Substantive claims about the target — phone attributes, country associations, format details. Generic collection log entries are collapsed below.</p>
      <table><tr><th>Statement</th><th>Status</th><th>Confidence</th></tr>{intel_rows}</table>
      <details style='margin-top:14px;'><summary class='hint'>Show {len(collection_claims)} collection log entries</summary>
        <table><tr><th>Statement</th><th>Status</th></tr>{collection_summary_rows}</table>
      </details>
    </div></section>

    <section class='section'><h2>📞 Phone Intelligence</h2><div class='pad split'>
      <div>
        <dl class='kv'>
          <dt>E.164</dt><dd><code>{html.escape(parsed.get('e164', 'n/a'))}</code></dd>
          <dt>Local</dt><dd>{html.escape(parsed.get('local', 'n/a'))}</dd>
          <dt>International</dt><dd>{html.escape(parsed.get('international', 'n/a'))}</dd>
          <dt>Country</dt><dd>{html.escape(parsed.get('country', 'n/a'))}</dd>
        </dl>
      </div>
      <div>
        <strong>Top OSINT Findings:</strong>
        <ul style='margin-top:6px;'>{finding_items}</ul>
      </div>
    </div></section>

    <section class='section'><h2>📅 Timeline</h2><div class='pad'>
      <table><tr><th style='width:160px;'>Time</th><th>Event</th><th>Conf.</th></tr>{timeline_rows}</table>
    </div></section>

    <section class='section'><h2>⚠ Contradictions</h2><div class='pad'>
      <table><tr><th>Claim</th><th>Conflicting Claim</th><th>Type</th></tr>{contradiction_rows}</table>
    </div></section>

    <section class='section'><h2>🔎 Search Pivots</h2><div class='pad'>
      <p class='hint'>Collection pivots generated by OSINT tools. Google zero-result pages are expected for some queries and do not invalidate claims.</p>
      {url_sections}
    </div></section>

    <details class='section' style='border:1px solid var(--border);border-radius:14px;margin-top:16px;'>
      <summary style='padding:13px 16px;background:#ecf3ef;border-bottom:1px solid var(--border);font-size:14px;text-transform:uppercase;letter-spacing:.4px;color:var(--accent2);cursor:pointer;font-weight:600;'>Raw Evidence Extract (click to expand)</summary>
      <div class='pad'><pre>{html.escape(meta.get('_log_excerpt', ''))}</pre></div>
    </details>
  </div>
</body>
</html>
"""


def build_phone_claims(parsed: dict[str, Any], target: str) -> list[dict[str, Any]]:
    entities_base = [{"role": "subject", "entity_type": "observable", "entity_value": target}]
    claims: list[dict[str, Any]] = []
    if parsed.get("country"):
        claims.append(
            {
                "statement": f"Phone number {target} is associated with country {parsed['country']}",
                "entities": entities_base + [{"role": "location", "entity_type": "location", "entity_value": parsed["country"]}],
                "claim_value": {"country": parsed["country"], "observable_type": "phone"},
                "metadata": {"source_layer": "phone_osint", "parser": "legacy-bridge", "field": "country"},
                "confidence": 0.81,
            }
        )
    if parsed.get("local"):
        claims.append(
            {
                "statement": f"Phone number {target} has local normalized form {parsed['local']}",
                "entities": entities_base + [{"role": "format", "entity_type": "observable", "entity_value": parsed["local"]}],
                "claim_value": {"local": parsed["local"], "observable_type": "phone"},
                "metadata": {"source_layer": "phone_osint", "parser": "legacy-bridge", "field": "local"},
                "confidence": 0.74,
            }
        )
    if parsed.get("international"):
        claims.append(
            {
                "statement": f"Phone number {target} has international normalized form {parsed['international']}",
                "entities": entities_base + [{"role": "format", "entity_type": "observable", "entity_value": parsed["international"]}],
                "claim_value": {"international": parsed["international"], "observable_type": "phone"},
                "metadata": {"source_layer": "phone_osint", "parser": "legacy-bridge", "field": "international"},
                "confidence": 0.74,
            }
        )
    if parsed.get("categories"):
        claims.append(
            {
                "statement": f"Phone number {target} produced multiple open-source search pivots across phone intelligence categories",
                "entities": entities_base,
                "claim_value": {"categories": {key: len(value) for key, value in parsed['categories'].items()}},
                "metadata": {"source_layer": "phone_osint", "parser": "legacy-bridge", "field": "search_surface"},
                "confidence": 0.68,
            }
        )
    return claims


def build_generic_claim(meta: dict[str, Any]) -> dict[str, Any]:
    profile = str(meta.get("profile") or "legacy")
    target = normalize_target_value(profile, str(meta.get("target") or "unknown"))
    profile = str(meta.get("profile") or "legacy")
    status = str(meta.get("status") or "unknown")
    label = strip_ansi(str(meta.get("label") or profile))
    duration = meta.get("duration_sec")
    lines = meta.get("line_count")
    detail_parts = []
    if duration:
        detail_parts.append(f"{duration}s runtime")
    if lines:
        detail_parts.append(f"{lines} lines collected")
    detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
    return {
        "statement": f"{profile_display_name(profile)} scan of '{target}' completed with status '{status}'{detail}",
        "entities": [{"role": "subject", "entity_type": infer_entity_type(profile, target), "entity_value": target}],
        "claim_value": {
            "profile": profile,
            "status": status,
            "exit_code": meta.get("exit_code"),
            "duration_sec": meta.get("duration_sec"),
            "line_count": meta.get("line_count"),
        },
        "metadata": {"source_layer": "legacy_dossier", "parser": "legacy-bridge", "field": "run_status", "label": meta.get("label")},
        "confidence": 0.66 if status == "success" else 0.35,
    }


def build_cross_entity_claims(metas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create claims that link entities across different profile types."""
    phones: list[str] = []
    identities: list[str] = []
    infra: list[str] = []
    for m in metas:
        profile = str(m.get("profile") or "")
        target = normalize_target_value(profile, str(m.get("target") or ""))
        profile = str(m.get("profile") or "")
        if not target or m.get("status") != "success":
            continue
        if profile == "phone" and target not in phones:
            phones.append(target)
        elif profile == "username" and target not in identities:
            identities.append(target)
        elif profile in ("domain", "whatweb", "dnsenum") and target not in infra:
            infra.append(target)

    claims: list[dict[str, Any]] = []
    # Link each phone to each identity
    for phone in phones:
        for identity in identities:
            claims.append({
                "statement": f"Phone {phone} is associated with identity '{identity}' based on co-occurrence in the same OSINT collection session",
                "entities": [
                    {"role": "subject", "entity_type": "observable", "entity_value": phone},
                    {"role": "owner", "entity_type": "identity", "entity_value": identity},
                ],
                "claim_value": {"link_type": "phone-to-identity", "phone": phone, "identity": identity},
                "metadata": {"source_layer": "cross_entity", "parser": "legacy-bridge", "field": "session_link"},
                "confidence": 0.62,
            })
    # Link each identity to each infrastructure target
    for identity in identities:
        for domain in infra:
            claims.append({
                "statement": f"Identity '{identity}' is linked to web resource '{domain}' based on co-occurrence in the same OSINT collection",
                "entities": [
                    {"role": "subject", "entity_type": "identity", "entity_value": identity},
                    {"role": "resource", "entity_type": "infrastructure", "entity_value": domain},
                ],
                "claim_value": {"link_type": "identity-to-infrastructure", "identity": identity, "resource": domain},
                "metadata": {"source_layer": "cross_entity", "parser": "legacy-bridge", "field": "session_link"},
                "confidence": 0.58,
            })
    # Link phones to infrastructure
    for phone in phones:
        for domain in infra:
            claims.append({
                "statement": f"Phone {phone} is linked to web resource '{domain}' via shared OSINT collection context",
                "entities": [
                    {"role": "subject", "entity_type": "observable", "entity_value": phone},
                    {"role": "resource", "entity_type": "infrastructure", "entity_value": domain},
                ],
                "claim_value": {"link_type": "phone-to-infrastructure", "phone": phone, "resource": domain},
                "metadata": {"source_layer": "cross_entity", "parser": "legacy-bridge", "field": "session_link"},
                "confidence": 0.52,
            })
    # Link multiple phones to each other
    for i, phone_a in enumerate(phones):
        for phone_b in phones[i + 1:]:
            claims.append({
                "statement": f"Phone numbers {phone_a} and {phone_b} are associated with the same target entity",
                "entities": [
                    {"role": "subject", "entity_type": "observable", "entity_value": phone_a},
                    {"role": "alias", "entity_type": "observable", "entity_value": phone_b},
                ],
                "claim_value": {"link_type": "phone-to-phone", "phones": [phone_a, phone_b]},
                "metadata": {"source_layer": "cross_entity", "parser": "legacy-bridge", "field": "multi_phone"},
                "confidence": 0.55,
            })
    return claims


def merge_parsed_results(parsed_results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"categories": {}, "urls": [], "top_findings": []}
    for parsed in parsed_results:
        for key in ("e164", "local", "international", "country"):
            if parsed.get(key) and not merged.get(key):
                merged[key] = parsed[key]
        for group_name, urls in parsed.get("categories", {}).items():
            merged["categories"].setdefault(group_name, []).extend(urls)
        merged["urls"].extend(parsed.get("urls", []))
        merged["top_findings"].extend(parsed.get("top_findings", []))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge legacy dossier exports into the control-plane API and render a connected HTML dossier.")
    parser.add_argument("--meta-json", required=True, nargs="+", help="Path(s) to legacy flat metadata JSON export(s).")
    parser.add_argument("--api-base", default="http://127.0.0.1:8700", help="Control-plane API base URL.")
    parser.add_argument("--api-token", default=DEFAULT_API_TOKEN, help="Bearer token for control-plane API access.")
    parser.add_argument("--output-html", help="Output HTML path. Defaults to runs/exports/html/dossiers/connected_<session>.html")
    args = parser.parse_args()

    meta_paths = [Path(item).expanduser().resolve() for item in args.meta_json]
    metas: list[dict[str, Any]] = []
    parsed_results: list[dict[str, Any]] = []
    log_payloads: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for meta_path in meta_paths:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta.get("log_file"):
            continue
        if meta.get("target"):
            meta["target"] = normalize_target_value(str(meta.get("profile") or ""), str(meta["target"]))
        if meta.get("label"):
            meta["label"] = strip_ansi(str(meta["label"]))
        log_path = Path(meta["log_file"]).expanduser().resolve()
        if not log_path.exists():
            continue
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_phone_log(log_text) if str(meta.get("profile")) == "phone" else {"categories": {}, "urls": [], "top_findings": []}
        meta["_log_excerpt"] = "\n".join(log_text.splitlines()[:120])
        metas.append(meta)
        parsed_results.append(parsed)
        log_payloads.append((meta, log_text, parsed))

    parsed = merge_parsed_results(parsed_results)
    meta_path = meta_paths[0]

    session_id_match = re.search(r"(\d{8}_\d{6})", meta_path.name)
    session_id = session_id_match.group(1) if session_id_match else datetime.now().strftime("%Y%m%d_%H%M%S")
    target = str(parsed.get("e164") or metas[0].get("target") or "unknown")

    health_status, health_payload = api_request(args.api_base, "GET", "/api/v1/health", api_token=args.api_token)
    if health_status != 200:
        raise RuntimeError(f"control-plane API is not reachable: {health_payload}")

    graph_id = ensure_graph(args.api_base, target, args.api_token)
    status, graph_payload = api_request(args.api_base, "GET", f"/api/v1/graphs/{graph_id}", api_token=args.api_token)
    if status != 200:
        raise RuntimeError(f"failed to fetch graph after creation: {graph_payload}")
    processor_node_id = str(graph_payload["graph_json"]["nodes"][1]["id"])

    run_id = create_run(args.api_base, graph_id, target, args.api_token)
    all_evidence_ids: list[str] = []
    evidence_ids_by_target: dict[str, list[str]] = {}
    for meta, log_text, parsed_item in log_payloads:
        post_event(args.api_base, run_id, processor_node_id, args.api_token, f"legacy dossier imported: {meta.get('label', meta.get('profile', 'unknown'))}")
        evidence_id = intake_evidence(args.api_base, run_id, processor_node_id, meta, log_text, args.api_token)
        all_evidence_ids.append(evidence_id)
        target_key = canonical_lookup_value(str(meta.get("target") or ""))
        if target_key:
            evidence_ids_by_target.setdefault(target_key, []).append(evidence_id)

        claims = [build_generic_claim(meta)]
        if str(meta.get("profile")) == "phone":
            claims.extend(build_phone_claims(parsed_item, str(parsed_item.get("e164") or meta.get("target") or target)))

        for claim in claims:
            claim_id = create_claim(args.api_base, run_id, claim["statement"], claim["entities"], claim["claim_value"], claim["metadata"], args.api_token)
            attach_evidence(args.api_base, claim_id, evidence_id, args.api_token, confidence=claim["confidence"])
            assess_claim(args.api_base, claim_id, args.api_token)

    # Cross-entity linking: connect phones, identities, and infrastructure
    cross_claims = build_cross_entity_claims(metas)
    if cross_claims and all_evidence_ids:
        for claim in cross_claims:
            claim_id = create_claim(args.api_base, run_id, claim["statement"], claim["entities"], claim["claim_value"], claim["metadata"], args.api_token)
            for supporting_id in supporting_evidence_ids(claim, evidence_ids_by_target) or all_evidence_ids[:1]:
                attach_evidence(args.api_base, claim_id, supporting_id, args.api_token, confidence=claim["confidence"])
            assess_claim(args.api_base, claim_id, args.api_token)

    dossier = fetch_json(args.api_base, f"/api/v1/runs/{run_id}/dossier", args.api_token)
    timeline = fetch_json(args.api_base, f"/api/v1/fusion/timeline/{run_id}", args.api_token)
    contradictions = fetch_json(args.api_base, f"/api/v1/fusion/contradictions/{run_id}", args.api_token)

    output_path = Path(args.output_html).expanduser().resolve() if args.output_html else meta_path.parent / "html" / "dossiers" / f"connected_{session_id}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path = output_path.parent / "latest_dossier.html"
    rendered = render_html(session_id, metas, parsed, dossier, timeline, contradictions)
    output_path.write_text(rendered, encoding="utf-8")
    latest_path.write_text(rendered, encoding="utf-8")

    print(json.dumps({
        "run_id": run_id,
        "graph_id": graph_id,
        "evidence_id": evidence_id,
        "output_html": str(output_path),
        "latest_html": str(latest_path),
        "claims": len(dossier.get("claims", [])),
        "entities": len(dossier.get("entities", [])),
        "relationships": len(dossier.get("relationships", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()