# HANNA Prelaunch Summary Contract

`final-summary.json` is the machine-readable release gate artifact produced by `./scripts/prelaunch_check.sh`.

The documented contract file lives at:

- [src/schemas/prelaunch_final_summary.schema.json](/Users/admin/Desktop/hanna-v3-2-clean/src/schemas/prelaunch_final_summary.schema.json)

## Minimum Contract

The file is expected to provide:

1. top-level release verdict: `overall_status`, `failure_count`, `stage_count`
2. stage-by-stage execution results in `stages[]`
3. stable grouped checks in `checks.preflight`, `checks.smart_summary`, `checks.focused_regression`, `checks.live_smoke`, `checks.full_rollout_rehearsal`
4. schema pinning through `schema_version`

## CI Gate

Use the dedicated gate script instead of parsing shell output:

```bash
./scripts/prelaunch_gate.sh .cache/prelaunch/<timestamp>/final-summary.json
```

For `make`-driven CI:

```bash
make prelaunch-gate SUMMARY=.cache/prelaunch/<timestamp>/final-summary.json
```

Exit codes:

1. `0` — schema valid and `overall_status == pass`
2. `1` — schema valid but gate conditions failed, including `overall_status != pass` or any `--require-check` target not equal to `pass`
3. `2` — invalid or incomplete `final-summary.json`

For machine-only pipelines:

```bash
./scripts/prelaunch_gate.sh \
  .cache/prelaunch/<timestamp>/final-summary.json \
  --json-only
```

To require a specific check block to pass:

```bash
./scripts/prelaunch_gate.sh \
  .cache/prelaunch/<timestamp>/final-summary.json \
  --require-check full_rollout_rehearsal \
  --json-only
```

`--require-check` may be provided multiple times. It currently accepts:

1. `preflight`
2. `smart_summary`
3. `focused_regression`
4. `live_smoke`
5. `full_rollout_rehearsal`

If a pipeline only wants schema validation and intends to inspect the release decision separately:

```bash
./scripts/prelaunch_gate.sh \
  .cache/prelaunch/<timestamp>/final-summary.json \
  --allow-fail \
  --json-only
```

`--allow-fail` only suppresses the top-level `overall_status` gate. It does not suppress failures introduced through `--require-check`.

## Stability Rule

External automation should treat these keys as stable contract fields:

1. `schema_version`
2. `overall_status`
3. `failure_count`
4. `stage_count`
5. `stages`
6. `checks`

Other fields may grow over time, but these fields must remain readable across prelaunch iterations.