# Schemas

This package contains planned schema models used for future workflow graph and STIX export capabilities.

These models are currently design-time artifacts and are intentionally kept separate from active runtime orchestration code.

## AdapterResult — Canonical Contract

`AdapterResult` is the authoritative envelope for the outcome of a single adapter execution.

| Field | Type | Default | Description |
|---|---|---|---|
| `status` | `"ok" \| "error" \| "timeout" \| "skipped"` | `"ok"` | Terminal status of the adapter run |
| `evidence` | `list[dict]` | `[]` | Collected evidence artefacts |
| `observables` | `list[dict]` | `[]` | Extracted observables (phones, emails, IPs, …) |
| `errors` | `list[str]` | `[]` | Human-readable error descriptions |
| `timings` | `dict[str, float]` | `{}` | Named timing measurements in seconds |
| `opsec_flags` | `list[str]` | `[]` | OPSEC warnings raised during the run |

### Invariants

- `status == "error"` implies `errors` is non-empty (auto-filled with `"unspecified error"` when empty).
- All fields are optional with safe empty defaults — callers may omit any field.

### Helpers

| Function | Description |
|---|---|
| `normalize_legacy_payload(raw)` | Coerces a legacy or unstructured `dict` into `AdapterResult`-compatible shape, mapping common alternate field names (`hits→observables`, `artifacts→evidence`, etc.) |
| `validate_result_outcomes(payload)` | Parses and validates a payload against `AdapterResult`; raises `ValueError` with a machine-readable JSON error on failure |
