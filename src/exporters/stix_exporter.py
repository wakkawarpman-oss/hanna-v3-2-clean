from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from models import RunResult


_NS = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unknown"


def _timestamp_fragment(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14] or "00000000000000"


def _stix_id(stix_type: str, seed: str) -> str:
    return f"{stix_type}--{uuid.uuid5(_NS, seed)}"


def build_stix_bundle(result: RunResult) -> dict[str, object]:
    created = (result.finished_at or result.started_at or "1970-01-01T00:00:00")
    identity_id = _stix_id("identity", f"identity:{result.target_name}")
    objects: list[dict[str, object]] = [
        {
            "type": "identity",
            "spec_version": "2.1",
            "id": identity_id,
            "created": created,
            "modified": created,
            "name": result.target_name,
            "identity_class": "individual",
        }
    ]

    for index, hit in enumerate(result.all_hits):
        observed_id = _stix_id("observed-data", f"observed:{result.mode}:{index}:{hit.fingerprint}")
        sco_type = {
            "email": "email-addr",
            "domain": "domain-name",
            "url": "url",
            "phone": "telephone-number",
            "username": "user-account",
        }.get(hit.observable_type, "artifact")
        if sco_type == "email-addr":
            sco = {"type": sco_type, "value": hit.value}
        elif sco_type == "domain-name":
            sco = {"type": sco_type, "value": hit.value}
        elif sco_type == "url":
            sco = {"type": sco_type, "value": hit.value}
        elif sco_type == "telephone-number":
            sco = {"type": sco_type, "value": hit.value}
        elif sco_type == "user-account":
            sco = {"type": sco_type, "account_login": hit.value}
        else:
            sco = {"type": sco_type, "mime_type": "text/plain", "payload_bin": hit.value}

        objects.append(
            {
                "type": "observed-data",
                "spec_version": "2.1",
                "id": observed_id,
                "created": created,
                "modified": created,
                "first_observed": created,
                "last_observed": created,
                "number_observed": 1,
                "objects": {"0": sco},
            }
        )
        objects.append(
            {
                "type": "relationship",
                "spec_version": "2.1",
                "id": _stix_id("relationship", f"relationship:{identity_id}:{observed_id}"),
                "created": created,
                "modified": created,
                "relationship_type": "related-to",
                "source_ref": identity_id,
                "target_ref": observed_id,
            }
        )

    objects.append(
        {
            "type": "note",
            "spec_version": "2.1",
            "id": _stix_id("note", f"note:{result.target_name}:{created}"),
            "created": created,
            "modified": created,
            "content": json.dumps(
                {
                    "mode": result.mode,
                    "modules_run": result.modules_run,
                    "errors": result.errors,
                    "extra": result.extra,
                },
                ensure_ascii=False,
            ),
            "object_refs": [identity_id],
        }
    )

    return {
        "type": "bundle",
        "id": _stix_id("bundle", f"bundle:{result.target_name}:{created}:{result.mode}"),
        "objects": objects,
    }


def export_run_result_stix(result: RunResult, output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_slugify(result.target_name)}-{result.mode}-{_timestamp_fragment(result.finished_at or result.started_at)}.stix.json"
    path.write_text(json.dumps(build_stix_bundle(result), indent=2, ensure_ascii=False), encoding="utf-8")
    return path