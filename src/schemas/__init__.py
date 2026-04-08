"""Schema models for workflow/STIX integrations and adapter output contracts."""

from .adapter_result import AdapterResult, normalize_legacy_payload, validate_result_outcomes

__all__ = [
    "AdapterResult",
    "normalize_legacy_payload",
    "validate_result_outcomes",
]
