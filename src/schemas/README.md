# Schemas

This package contains Pydantic schema models used for workflow graph, STIX
export, and **adapter result validation**.

## AdapterResult (canonical adapter contract)

`AdapterResult` is the canonical schema for every adapter execution result.
All adapter runners produce an `AdapterOutcome`; at the export boundary
(``cli._export_result_artifacts``) each outcome is normalised and validated
against this schema before any file is written.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | `AdapterResultStatus` | ✓ | `ok` · `error` · `timeout` · `skipped` |
| `evidence` | `list[EvidenceItem]` | — | Artifact references (logs, reports, …) |
| `observables` | `list[ObservableItem]` | — | Extracted entities (phone, email, …) |
| `errors` | `list[str]` | — | Human-readable error messages |
| `timings` | `TimingInfo` | — | `elapsed_sec`, `started_at`, `finished_at` |
| `opsec_flags` | `list[OpsecFlag]` | — | Operational-security flags |

### Backward compatibility

Legacy `AdapterOutcome.to_dict()` payloads are automatically normalised to
the canonical format by `normalize_legacy_payload()` before validation, so
existing adapters require no changes.

### Usage

```python
from schemas import AdapterResult, normalize_legacy_payload, validate_adapter_outcomes

# Validate a single legacy payload
raw = outcome.to_dict()
normalized = normalize_legacy_payload(raw)
result = AdapterResult.model_validate(normalized)

# Bulk-validate all outcomes in a RunResult (raises AdapterPayloadValidationError on failure)
validate_adapter_outcomes(run_result.outcomes)
```

## Workflow / STIX models

`pydantic_models.py` contains design-time schema models for future workflow
graph and STIX 2.1 export capabilities.  These are intentionally kept
separate from active runtime orchestration code.
