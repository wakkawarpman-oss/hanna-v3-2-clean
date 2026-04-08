"""
adapter_result.py — Canonical Pydantic model for adapter run outcomes.

Defines AdapterResult, the contract envelope returned by every adapter
execution path, plus helpers for normalising legacy payloads and
validating run outcomes before export.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class AdapterResult(BaseModel):
    """Canonical result envelope produced by a single adapter execution."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error", "timeout", "skipped"] = "ok"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    observables: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    opsec_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _error_status_requires_errors(self) -> "AdapterResult":
        if self.status == "error" and not self.errors:
            self.errors = ["unspecified error"]
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_legacy_payload(raw: Any) -> dict[str, Any]:
    """Coerce a legacy or unstructured payload dict into AdapterResult-compatible shape.

    Missing optional fields are filled with safe empty defaults so that
    downstream consumers never encounter KeyError on well-known keys.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"normalize_legacy_payload: cannot parse JSON string: {exc}") from exc

    if not isinstance(raw, dict):
        raise TypeError(f"normalize_legacy_payload: expected dict or JSON string, got {type(raw).__name__}")

    normalised: dict[str, Any] = {
        "status": raw.get("status", "ok"),
        "evidence": raw.get("evidence", raw.get("artifacts", [])),
        "observables": raw.get("observables", raw.get("hits", [])),
        "errors": raw.get("errors", []),
        "timings": raw.get("timings", raw.get("timing", {})),
        "opsec_flags": raw.get("opsec_flags", raw.get("opsec", [])),
    }

    # Coerce common single-string error to list
    if isinstance(normalised["errors"], str):
        normalised["errors"] = [normalised["errors"]] if normalised["errors"] else []

    # Coerce list of strings to list of dicts for evidence / observables if needed
    for key in ("evidence", "observables"):
        if isinstance(normalised[key], list):
            normalised[key] = [
                item if isinstance(item, dict) else {"value": item}
                for item in normalised[key]
            ]

    return normalised


def validate_result_outcomes(payload: Any) -> AdapterResult:
    """Parse and validate an adapter result payload against AdapterResult.

    Accepts a dict (raw or already normalised) or an AdapterResult instance.
    On validation failure raises ``ValueError`` with a deterministic,
    machine-readable JSON description of every field error.

    Returns the validated ``AdapterResult``.
    """
    if isinstance(payload, AdapterResult):
        return payload

    try:
        normalised = normalize_legacy_payload(payload)
    except (TypeError, ValueError) as exc:
        _raise_validation_error([{"loc": ["__root__"], "msg": str(exc), "type": "value_error"}])

    from pydantic import ValidationError

    try:
        return AdapterResult.model_validate(normalised)
    except ValidationError as exc:
        _raise_validation_error(exc.errors())


def _raise_validation_error(errors: list[dict[str, Any]]) -> None:
    """Raise ``ValueError`` with a machine-readable JSON error payload."""
    payload = json.dumps(
        {"schema": "AdapterResult", "errors": errors},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise ValueError(payload)
