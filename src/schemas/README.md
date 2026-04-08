# Schemas

This package contains schema models used for workflow graph, STIX export, and
adapter result validation.

## Canonical AdapterResult contract

`AdapterResult` is the single source of truth for what a validated adapter
execution result looks like at the export boundary.

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `status` | `str` | **required** | Execution status: `"ok"`, `"error"`, or `"skipped"` |
| `evidence` | `list[dict]` | `[]` | Raw or normalised evidence artifacts |
| `observables` | `list[dict]` | `[]` | Extracted observables (phone, email, IP, …) |
| `errors` | `list[str]` | `[]` | Human-readable error messages |
| `timings` | `dict[str, float]` | `{}` | Labelled timing measurements in seconds |
| `opsec_flags` | `list[str]` | `[]` | Active OPSEC constraints for this result |

### Helper functions

**`normalize_legacy_payload(payload: dict) -> dict`**
Coerces a raw adapter payload dict (which may use legacy field names such as
`ok`, `hits`, `elapsed_sec`) into a dict that is safe to pass to
`AdapterResult(**…)`.  All optional fields receive backward-compatible defaults
if absent.

**`validate_result_outcomes(outcomes: list[dict]) -> list[AdapterResult]`**
Validates a list of raw outcome dicts (e.g. from `AdapterOutcome.to_dict()`).
Each element is normalised via `normalize_legacy_payload` and then validated by
the Pydantic model.  If *any* outcome fails schema validation the function
raises a `ValueError` containing a deterministic, machine-readable error object:

```json
{
  "message": "One or more adapter outcomes failed schema validation",
  "failed_count": 1,
  "total_count": 3,
  "validation_errors": [
    {
      "index": 1,
      "module_name": "ua_phone",
      "error_type": "validation_error",
      "detail": [...]
    }
  ]
}
```

### CLI integration

`_export_result_artifacts` in `cli.py` calls `validate_result_outcomes` before
writing any artifacts.  Malformed outcomes are rejected immediately with a
`RuntimeError` so that corrupted data never reaches disk.

