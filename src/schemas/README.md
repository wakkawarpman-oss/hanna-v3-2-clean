# Schemas

This package contains schema models used for workflow graph, STIX export, and adapter output contracts.

## Canonical AdapterResult Contract

`AdapterResult` (`src/schemas/adapter_result.py`) is the authoritative Pydantic model for every adapter's output.

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `str` | ✅ | Execution status: `"ok"`, `"error"`, `"timeout"`, etc. |
| `evidence` | `list[dict]` | — | Structured evidence artefacts emitted by the adapter. |
| `observables` | `list[dict]` | — | Observable entities (phones, emails, domains …). |
| `errors` | `list[str]` | — | Human-readable error messages collected during execution. |
| `timings` | `dict[str, float]` | — | Named timing measurements in seconds. |
| `opsec_flags` | `list[str]` | — | OPSEC concern tags (e.g. `"dns_leak"`). |

### Helpers

- **`normalize_legacy_payload(payload)`** — Maps legacy dict shapes to the canonical field set before validation. Handles common aliases (`hits→observables`, `error→errors`, `elapsed_sec→timings`, status aliases).
- **`validate_result_outcomes(outcomes)`** — Validates a list of raw outcome dicts; returns `list[AdapterResult]` or raises a deterministic `ValueError` with a machine-readable JSON payload.

### Usage

```python
from schemas import validate_result_outcomes, normalize_legacy_payload, AdapterResult

# Validate a list of raw adapter outputs at the export boundary
validated = validate_result_outcomes(raw_outcomes)
```

