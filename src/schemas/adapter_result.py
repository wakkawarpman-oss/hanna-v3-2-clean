"""
adapter_result.py — Canonical AdapterResult schema and validation helpers.

Provides:
    AdapterResult          — Pydantic model wrapping a single adapter execution result.
    normalize_legacy_payload(payload) — Coerce a raw dict into AdapterResult-compatible form.
    validate_result_outcomes(outcomes) — Validate a list of raw outcome dicts; raise on malformed.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AdapterResult(BaseModel):
    """Canonical result envelope for a single adapter execution."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(..., min_length=1, description="Execution status: 'ok' | 'error' | 'skipped'")
    evidence: list[dict[str, Any]] = Field(default_factory=list, description="Raw or normalised evidence artifacts")
    observables: list[dict[str, Any]] = Field(default_factory=list, description="Extracted observables (phone, email, IP, …)")
    errors: list[str] = Field(default_factory=list, description="Human-readable error messages")
    timings: dict[str, float] = Field(default_factory=dict, description="Labelled timing measurements in seconds")
    opsec_flags: list[str] = Field(default_factory=list, description="Active OPSEC constraints for this result")


def normalize_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw adapter payload dict into AdapterResult-compatible form.

    Handles legacy field aliases and fills backward-compatible defaults so that
    callers do not need to pre-process before constructing AdapterResult.

    Args:
        payload: Raw dict from an adapter run; may use legacy field names.

    Returns:
        A dict suitable for ``AdapterResult(**result)``.
    """
    out: dict[str, Any] = {}

    # status: legacy adapters used 'ok' (bool) or 'result'
    if "status" in payload:
        out["status"] = str(payload["status"])
    elif "ok" in payload:
        out["status"] = "ok" if payload["ok"] else "error"
    elif payload.get("error"):
        # Infer error status from presence of a non-empty error field
        out["status"] = "error"
    else:
        out["status"] = "ok"

    # evidence / hits
    if "evidence" in payload:
        out["evidence"] = list(payload["evidence"])
    elif "hits" in payload:
        raw_hits = payload["hits"]
        out["evidence"] = [h if isinstance(h, dict) else {"value": str(h)} for h in raw_hits]
    else:
        out["evidence"] = []

    # observables
    if "observables" in payload:
        out["observables"] = list(payload["observables"])
    elif "all_hits" in payload:
        raw = payload["all_hits"]
        out["observables"] = [h if isinstance(h, dict) else {"value": str(h)} for h in raw]
    else:
        out["observables"] = []

    # errors
    if "errors" in payload:
        raw_errors = payload["errors"]
        out["errors"] = [
            e if isinstance(e, str) else str(e.get("error", e))
            for e in raw_errors
        ]
    elif "error" in payload and payload["error"]:
        out["errors"] = [str(payload["error"])]
    else:
        out["errors"] = []

    # timings
    if "timings" in payload:
        out["timings"] = {k: float(v) for k, v in payload["timings"].items()}
    elif "elapsed_sec" in payload and payload["elapsed_sec"] is not None:
        out["timings"] = {"elapsed_sec": float(payload["elapsed_sec"])}
    else:
        out["timings"] = {}

    # opsec_flags
    if "opsec_flags" in payload:
        out["opsec_flags"] = [str(f) for f in payload["opsec_flags"]]
    else:
        out["opsec_flags"] = []

    return out


def validate_result_outcomes(outcomes: list[dict[str, Any]]) -> list[AdapterResult]:
    """Validate a list of raw outcome dicts and return parsed AdapterResult objects.

    Each element is first normalised via :func:`normalize_legacy_payload` and then
    validated by the Pydantic model.  If *any* outcome fails validation the function
    raises a :class:`ValueError` containing a deterministic, machine-readable error
    object so that callers can fail fast at the export boundary.

    Args:
        outcomes: List of raw outcome dicts (e.g. from ``AdapterOutcome.to_dict()``).

    Returns:
        List of validated :class:`AdapterResult` instances.

    Raises:
        ValueError: If one or more outcomes fail schema validation.
    """
    errors: list[dict[str, Any]] = []
    results: list[AdapterResult] = []

    for idx, raw in enumerate(outcomes):
        if not isinstance(raw, dict):
            errors.append({
                "index": idx,
                "error_type": "type_error",
                "detail": f"Expected dict, got {type(raw).__name__}",
            })
            continue
        normalised = normalize_legacy_payload(raw)
        try:
            results.append(AdapterResult(**normalised))
        except ValidationError as exc:
            errors.append({
                "index": idx,
                "module_name": raw.get("module_name", "<unknown>"),
                "error_type": "validation_error",
                "detail": exc.errors(include_url=False),
            })

    if errors:
        raise ValueError({
            "message": "One or more adapter outcomes failed schema validation",
            "failed_count": len(errors),
            "total_count": len(outcomes),
            "validation_errors": errors,
        })

    return results
