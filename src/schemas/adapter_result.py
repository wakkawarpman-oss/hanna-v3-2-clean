"""
schemas.adapter_result — Canonical AdapterResult contract schema.

Every adapter run produces a payload that must conform to this schema before
it can be exported or persisted.  Legacy adapter payloads (dicts produced by
``AdapterOutcome.to_dict()``) are normalised by :func:`normalize_legacy_payload`
before validation, preserving backward compatibility.

Public API
----------
AdapterResult          — Pydantic model (the canonical envelope)
AdapterResultStatus    — Enum of valid status strings
ObservableItem         — A single extracted observable (phone, email, …)
EvidenceItem           — A single evidence artifact reference
TimingInfo             — Timing metadata for one adapter run
OpsecFlag              — An operational-security flag raised during execution

normalize_legacy_payload(raw)  — normalise a legacy outcome dict to AdapterResult
validate_adapter_outcomes(outcomes)  — bulk-validate a list of outcome objects/dicts
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class AdapterResultStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ObservableItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    observable_type: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    source_module: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str = Field(..., min_length=1)
    uri: str = Field(default="")


class TimingInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    elapsed_sec: float = Field(default=0.0, ge=0.0)
    started_at: str | None = None
    finished_at: str | None = None


class OpsecFlag(BaseModel):
    model_config = ConfigDict(extra="allow")

    flag: str = Field(..., min_length=1)
    severity: str = Field(default="info")
    detail: str | None = None


# ---------------------------------------------------------------------------
# Canonical envelope
# ---------------------------------------------------------------------------

class AdapterResult(BaseModel):
    """Canonical schema for a single adapter execution result."""

    model_config = ConfigDict(extra="allow")

    status: AdapterResultStatus
    evidence: list[EvidenceItem] = Field(default_factory=list)
    observables: list[ObservableItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    timings: TimingInfo = Field(default_factory=TimingInfo)
    opsec_flags: list[OpsecFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------

_ERROR_KIND_TO_STATUS: dict[str, str] = {
    "timeout": "timeout",
    "missing_credentials": "skipped",
    "missing_binary": "skipped",
    "dependency_unavailable": "skipped",
}


def normalize_legacy_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a legacy adapter outcome dict to the AdapterResult wire format.

    Accepts the dict produced by ``AdapterOutcome.to_dict()`` or any older
    ad-hoc adapter payload dict and maps it to the fields expected by
    :class:`AdapterResult`.  Unknown extra fields are passed through verbatim
    (``extra="allow"``).

    Parameters
    ----------
    raw:
        A dict that may contain any combination of the legacy keys
        (``module_name``, ``error``, ``error_kind``, ``hits``,
        ``log_path``, ``elapsed_sec``, …) as well as already-canonical
        AdapterResult keys.

    Returns
    -------
    dict
        A dict ready to be fed to ``AdapterResult.model_validate()``.
    """
    # If the dict already looks canonical (has a "status" key), return as-is.
    if "status" in raw:
        return dict(raw)

    # -- status --
    error_kind: str = str(raw.get("error_kind") or "")
    error_msg: str | None = raw.get("error") or None

    if error_kind in _ERROR_KIND_TO_STATUS:
        status = _ERROR_KIND_TO_STATUS[error_kind]
    elif error_msg:
        status = "error"
    else:
        status = "ok"

    # -- observables from hits list --
    hits: list[Any] = raw.get("hits") or []
    observables: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        value = str(hit.get("value") or "")
        if not value:
            continue
        observables.append(
            {
                "observable_type": str(hit.get("observable_type") or "unknown"),
                "value": value,
                "source_module": str(
                    hit.get("source_module") or raw.get("module_name") or ""
                ),
                "confidence": float(hit.get("confidence") or 0.0),
            }
        )

    # -- evidence from log_path --
    evidence: list[dict[str, Any]] = []
    log_path = raw.get("log_path") or ""
    if log_path:
        evidence.append({"kind": "execution_log", "uri": str(log_path)})

    # -- timings --
    elapsed = raw.get("elapsed_sec")
    timings: dict[str, Any] = {
        "elapsed_sec": float(elapsed) if elapsed is not None else 0.0,
    }
    if raw.get("started_at"):
        timings["started_at"] = str(raw["started_at"])
    if raw.get("finished_at"):
        timings["finished_at"] = str(raw["finished_at"])

    # -- errors --
    errors: list[str] = [error_msg] if error_msg else []

    return {
        "status": status,
        "evidence": evidence,
        "observables": observables,
        "errors": errors,
        "timings": timings,
        "opsec_flags": [],
    }


# ---------------------------------------------------------------------------
# Bulk validation helper (used by the CLI export boundary)
# ---------------------------------------------------------------------------

class AdapterPayloadValidationError(ValueError):
    """Raised when one or more adapter outcomes fail AdapterResult validation.

    The ``failures`` attribute contains a list of dicts with the keys
    ``module`` and ``validation_errors`` (Pydantic error list).
    """

    def __init__(self, failures: list[dict[str, Any]]) -> None:
        self.failures = failures
        body = json.dumps(failures, indent=2, ensure_ascii=False)
        super().__init__(f"adapter payload validation failed:\n{body}")


def validate_adapter_outcomes(outcomes: list[Any]) -> None:
    """Validate a sequence of adapter outcome objects against :class:`AdapterResult`.

    Each element may be an ``AdapterOutcome`` instance (with a ``.to_dict()``
    method) or a plain dict.  Legacy payloads are normalised via
    :func:`normalize_legacy_payload` before validation.

    Parameters
    ----------
    outcomes:
        Outcome objects or dicts produced by any adapter runner.

    Raises
    ------
    AdapterPayloadValidationError
        When one or more outcomes do not conform to the AdapterResult schema
        after normalisation.  All failures are aggregated before raising, so
        the caller sees every problem in a single exception.
    """
    failures: list[dict[str, Any]] = []

    for item in outcomes:
        raw: dict[str, Any] = (
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
        )
        module_name: str = str(raw.get("module_name") or "?")
        normalized = normalize_legacy_payload(raw)
        try:
            AdapterResult.model_validate(normalized)
        except ValidationError as exc:
            failures.append(
                {
                    "module": module_name,
                    "validation_errors": exc.errors(include_url=False),
                }
            )

    if failures:
        raise AdapterPayloadValidationError(failures)
