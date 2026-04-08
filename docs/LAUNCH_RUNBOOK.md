# HANNA Launch Runbook

This runbook defines the minimum operator flow before a controlled rollout.

## 1. Environment Freeze

Run from the repository root:

```bash
cd /Users/admin/Desktop/hanna-v3-2-clean
./scripts/setup_hanna.sh
```

Canonical cockpit launch for macOS and the VS Code integrated terminal:

```bash
./scripts/hanna ui --plain
```

Before rollout, freeze these surfaces:

- canonical launcher: `./scripts/hanna`
- legacy compatibility launchers: `python3 run_discovery.py`, `python3 hanna_ui.py`
- export contract: HTML + metadata + STIX + ZIP
- reset semantics: preserve or remove generated runtime state only through `rs`

## 2. Mandatory Pre-Launch Check

Run the bundled verification workflow:

```bash
./scripts/prelaunch_check.sh
```

This creates a review bundle under `.cache/prelaunch/<timestamp>/` containing:

- root wrapper smoke outputs
- canonical list/preflight JSON
- smart summary smoke output
- focused regression output
- final machine-readable verdict in `final-summary.json`

For CI or external automation, read only `final-summary.json` through the gate helper:

```bash
./scripts/prelaunch_gate.sh .cache/prelaunch/<timestamp>/final-summary.json
```

If CI must require a successful full rehearsal, not just a passing overall bundle:

```bash
./scripts/prelaunch_gate.sh \
	.cache/prelaunch/<timestamp>/final-summary.json \
	--require-check full_rollout_rehearsal
```

If you prefer `make` in CI:

```bash
make prelaunch-gate \
	SUMMARY=.cache/prelaunch/<timestamp>/final-summary.json \
	ARGS='--require-check full_rollout_rehearsal'
```

## 3. Optional Live Smoke

To include the no-credential chain smoke used during release QA:

```bash
HANNA_RUN_LIVE_SMOKE=1 ./scripts/prelaunch_check.sh
```

Use this only when you explicitly want a longer operational rehearsal.

To include a full chain rehearsal with artifact verification after HTML/STIX/ZIP generation:

```bash
HANNA_RUN_FULL_REHEARSAL=1 \
HANNA_FULL_REHEARSAL_TARGET="example.com" \
HANNA_FULL_REHEARSAL_MODULES="pd-infra-quick" \
./scripts/prelaunch_check.sh
```

The rehearsal writes:

- `full-rehearsal.runtime.json`
- `full-rehearsal.metadata.json`
- `full-rehearsal.verification.json`

`full-rehearsal.verification.json` is considered passing only if the generated HTML path exists and the exported `json`, `metadata`, `stix`, and `zip` files all exist.

## 4. Pass Criteria

Minimum pass criteria before rollout:

1. `run_discovery.py` root wrapper lists adapters and presets without crashing.
2. `hanna_ui.py` root wrapper exposes `tui` help without crashing.
3. `preflight.json` shows no blocking failures for the intended preset.
4. Focused regression bundle is fully green.
5. ZIP-export path remains intact, including hit-linked artifacts such as persisted EyeWitness output when produced.
6. `final-summary.json` reports overall `pass` for the intended gate.

The documented schema contract for this file is in [docs/PRELAUNCH_SUMMARY_SCHEMA.md](/Users/admin/Desktop/hanna-v3-2-clean/docs/PRELAUNCH_SUMMARY_SCHEMA.md).

## 5. Controlled Rollout Order

Use this order:

1. Internal smoke target.
2. Limited production target set.
3. Full operator rollout.

Do not add features during this window. Treat the first 24-48 hours as a stability observation period.

## 6. Immediate Rollback Conditions

Pause rollout if any of the following appear:

1. Entry-point drift returns and operators need `PYTHONPATH` workarounds.
2. ZIP bundles are missing dossier, metadata, STIX, or expected media artifacts.
3. Runtime summaries show unexpected `worker_crash` or broad timeout spikes.
4. Preflight begins failing on tools that were green at freeze time.

## 7. Post-Launch Observation

Watch these first:

1. `missing_credentials` versus true runtime failures.
2. `missing_binary` growth after environment changes.
3. incomplete artifact bundles.
4. stale or oversized runtime directories under the active runs root.