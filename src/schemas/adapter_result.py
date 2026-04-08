"""adapter_result.py — Canonical AdapterResult schema and validation helpers.

This module defines the authoritative Pydantic contract for adapter output,
plus two helpers used at the export boundary:

    normalize_legacy_payload(payload)
        Maps legacy dict shapes (pre-contract) into the canonical field set.

    validate_result_outcomes(outcomes)
        Validates a sequence of raw outcome dicts against AdapterResult;
        returns a list of validated AdapterResult instances or raises a
        deterministic ValueError with a machine-readable payload.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AdapterResult(BaseModel):
    """Canonical result envelope produced by every adapter execution."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(..., min_length=1, description="Execution status, e.g. 'ok', 'error', 'timeout'.")
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured evidence artefacts emitted by the adapter.",
    )
    observables: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Observable entities extracted from the run (phones, emails, domains …).",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Human-readable error messages collected during execution.",
    )
    timings: dict[str, float] = Field(
        default_factory=dict,
        description="Named timing measurements in seconds (e.g. {'elapsed_sec': 1.2}).",
    )
    opsec_flags: list[str] = Field(
        default_factory=list,
        description="OPSEC concern tags raised during execution (e.g. 'dns_leak', 'plaintext_exfil').",
    )


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------

_LEGACY_STATUS_MAP: dict[str, str] = {
    "success": "ok",
    "succeeded": "ok",
    "failure": "error",
    "failed": "error",
    "err": "error",
}


def normalize_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *payload* normalised to the canonical AdapterResult field set.

    Handles common legacy shapes:
    - ``result`` / ``outcome`` top-level wrapper keys are unwrapped.
    - ``status`` aliases (``success``, ``failure``, ``succeeded``, ``failed``, ``err``) are mapped.
    - ``hits`` is mapped to ``observables`` when ``observables`` is absent.
    - ``error`` (str) is promoted to ``errors`` list when ``errors`` is absent.
    - ``elapsed_sec`` is promoted to ``timings["elapsed_sec"]`` when ``timings`` is absent.
    """
    if not isinstance(payload, dict):
        return payload  # pass through; validation will reject it

    # Unwrap common wrapper keys
    if len(payload) == 1:
        sole_key = next(iter(payload))
        if sole_key in ("result", "outcome"):
            payload = payload[sole_key]
            if not isinstance(payload, dict):
                return payload

    out: dict[str, Any] = dict(payload)

    # Normalise status aliases
    raw_status = out.get("status")
    if isinstance(raw_status, str):
        out["status"] = _LEGACY_STATUS_MAP.get(raw_status.lower(), raw_status)
    elif raw_status is None and "status" not in out:
        # Derive status from error field (AdapterOutcome.to_dict() shape)
        out["status"] = "error" if out.get("error") is not None else "ok"

    # Promote hits → observables
    if "observables" not in out and "hits" in out:
        hits = out.pop("hits")
        out["observables"] = hits if isinstance(hits, list) else []

    # Promote single error string → errors list
    if "errors" not in out and "error" in out:
        err_val = out.get("error")
        out["errors"] = [err_val] if err_val is not None else []

    # Promote elapsed_sec → timings
    if "timings" not in out and "elapsed_sec" in out:
        elapsed = out.get("elapsed_sec")
        if isinstance(elapsed, (int, float)):
            out["timings"] = {"elapsed_sec": float(elapsed)}

    return out


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_result_outcomes(outcomes: list[dict[str, Any]]) -> list[AdapterResult]:
    """Validate a list of raw outcome dicts and return AdapterResult instances.

    Each element is first passed through :func:`normalize_legacy_payload` and
    then validated against :class:`AdapterResult`.

    Raises:
        ValueError: If any element fails validation.  The exception message is
            valid JSON with the following machine-readable shape::

                {
                  "error": "validate_result_outcomes_failed",
                  "failures": [
                    {"index": 0, "detail": "<pydantic error summary>"}
                  ]
                }
    """
    if not isinstance(outcomes, list):
        raise ValueError(
            json.dumps(
                {
                    "error": "validate_result_outcomes_failed",
                    "failures": [{"index": None, "detail": "outcomes must be a list"}],
                }
            )
        )

    validated: list[AdapterResult] = []
    failures: list[dict[str, Any]] = []

    for idx, raw in enumerate(outcomes):
        normalised = normalize_legacy_payload(raw) if isinstance(raw, dict) else raw
        try:
            validated.append(AdapterResult.model_validate(normalised))
        except ValidationError as exc:
            failures.append({"index": idx, "detail": exc.json(indent=None)})

    if failures:
        raise ValueError(
            json.dumps({"error": "validate_result_outcomes_failed", "failures": failures})
        )

    return validated
