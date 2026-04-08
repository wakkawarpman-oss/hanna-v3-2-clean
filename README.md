# HANNA v3.2 Clean

HANNA is a modular OSINT orchestration platform for running adapter-based collection, normalizing observables, resolving entities, and producing both operator-facing dossiers and machine-readable exports.

This repository is the clean canonical codebase published as `wakkawarpman-oss/hanna-v3-2-clean`.

## Current Status

The project is in late integration and release hardening.

Core platform capabilities are already present:

- Canonical CLI for `chain`, `aggregate`, `manual`, `preflight`, `list`, and `reset`
- Discovery engine with ingestion, observable registration, entity resolution, and verification flows
- Safe-by-default HTML dossier generation with `internal`, `shareable`, and `strict` redaction modes
- Canonical export surface for JSON, run metadata JSON, STIX-like bundles, and ZIP evidence packs
- Schema-validated smart summaries and deterministic risk-flag extraction for noisy analyst text
- Operator cleanup workflow for runtime DB, logs, reports, and generated artifacts
- Regression coverage for report redaction, export contracts, and reset behavior

Not yet shipped in the current runtime:

- LLM-backed smart summaries
- automated AI risk-flag extraction
- schema-validated prompt orchestration for analyst narratives

## Architecture

The repository is organized around four layers:

1. Adapters
   External tools and APIs are wrapped behind a shared adapter contract so they produce consistent hits and metadata.

2. Execution Runners
   `manual`, `aggregate`, and `chain` provide operator-friendly entrypoints for single-module runs, parallel module batches, and full discovery workflows.

3. Discovery Engine
   Normalizes observables, links corroborating evidence, resolves entities, tracks rejected targets, and renders dossiers.

4. Export and Ops Surface
   JSON, STIX, ZIP, preflight checks, and workspace reset give the system a stable operational shell.

## Repository Layout

- `src/cli.py` — canonical operator CLI
- `src/runners/` — execution modes and orchestration
- `src/discovery_engine.py` — ingestion, entity resolution, verification, and dossier rendering
- `src/adapters/` — integrated data-source wrappers
- `src/exporters/` — JSON, STIX, and ZIP exports
- `src/runtime_ops.py` — reset and cleanup helpers
- `tests/` — regression coverage for runners, exporters, CLI contracts, and discovery behavior

## Quick Start

```bash
cd hanna-v3-2-clean
./scripts/setup_hanna.sh
source .venv/bin/activate
./scripts/hanna pf
```

## TUI Quick Start

```bash
npm install
npm run tui
```

Ultra performance mode:

```bash
npm run tui:ultra
```

Prestart and production readiness:

```bash
npm run prestart:check
npm run production-readiness
# optional one-shot start after checks
npm run prestart:start
```

TUI search controls:

- `Ctrl+S` — open OSINT search window and focus input
- `Enter` — run multi-entity search routing
- `Ctrl+Enter` — load a sample query
- `Esc` — close search window

TUI debug controls:

- `Ctrl+D` — open parser debug panel
- `F1` — load debug sample query
- `F2` — clear debug widgets
- `F12` — toggle debug panel visibility

Smart search and behavioral commands:

```bash
npm run test:smart
npm run search:smart
npm run search:cluster
npm run behavioral:test
npm run tui:behavioral
```

Manual calibration workflow:

```bash
npm run calibrate
npm run calibrate:validate
npm run tui:calibrated
npm run calibrate:reset
```

Calibration values are stored in `config.calibrated.json` and applied when `CALIBRATED=1`.

## Production Deployment Template

This repo now includes production-ready deployment templates for Docker, PM2, Nginx, Prometheus, GitHub Actions, and systemd:

- `Dockerfile.prod`
- `docker-compose.prod.yml`
- `nginx.conf`
- `prometheus.yml`
- `ecosystem.config.js`
- `.github/workflows/deploy.yml`
- `deploy/systemd/hanna-parser.service`
- `deploy/systemd/hanna-healthcheck.service`
- `deploy/systemd/setup-hanna-user.sh`
- `deploy/systemd/deploy-hanna-systemd.sh`

Quick local production smoke:

```bash
cp .env.example .env.prod
docker compose -f docker-compose.prod.yml up --build
curl -fsS http://localhost:3000/health
```

Systemd deployment helper:

```bash
bash deploy/systemd/deploy-hanna-systemd.sh
```

Stress testing suite:

```bash
npm run stress:all
npm run stress:report
```

Optional heavy scenarios:

```bash
npm run stress:tui
npm run stress:disk
npm run stress:kill9
npm run stress:apocalypse
```

Notes:

- `stress:api` requires Artillery (`npx artillery ...`).
- `stress:all` runs a quick baseline by default; set `STRESS_TUI=1` and/or `STRESS_LONG=1` to include heavy runs.

API optimized runtime options:

```bash
npm run start:prod
npm run api:worker
npm run perf:monitor
```

Large file parsing and benchmarking:

```bash
npm run gen:test-files
npm run parse:large -- test/data/100mb.txt
npm run bench:files
```

Hanna quick command toolkit:

```bash
./scripts/install.sh
hanna start
hanna test
hanna contract
hanna tui
hanna stop
```

Use strict preflight before operational runs:

```bash
./scripts/hanna pf --strict
```

For fully automated operator shells, preflight can emit structured JSON only:

```bash
./scripts/hanna pf --modules ua_phone --json-only
./scripts/hanna ls --json-only --output-file ./runs/exports/inventory.json
```

For a shorter operator workflow, use the repo-local wrapper:

```bash
./scripts/hanna ls
./scripts/hanna ui --plain --target "Ivan" --modules full-spectrum
source scripts/hanna-aliases.sh
```

Canonical cockpit launch on macOS and in the VS Code integrated terminal:

```bash
./scripts/hanna ui --plain
```

To install a global `hanna` command without `source`, run:

```bash
./scripts/install_hanna_command.sh
```

This installs a symlink into `$HOME/.local/bin/hanna` and, by default, adds that directory to `$HOME/.zshrc` if needed.

Canonical operator entrypoint: `./scripts/hanna`.

Legacy compatibility entrypoint: `python3 src/run_discovery.py`.
Use it only for older scripts or legacy batch flows.

Root compatibility wrappers are also available for older automation that still expects repo-root scripts:

- `python3 run_discovery.py` → legacy discovery entrypoint
- `python3 hanna_ui.py` → forwards to `tui`

## Main Workflows

Run the full discovery pipeline and render a sanitized dossier:

```bash
./scripts/hanna ch \
  --target "Example Target" \
  --modules ua_leak,ghunt,opendatabot \
  --verify \
  --report-mode shareable \
  --export-formats json,metadata,stix,zip
```

Run selected adapters in parallel without dossier rendering:

```bash
./scripts/hanna agg \
  --target example.com \
  --modules full-spectrum \
  --workers 4 \
  --export-formats json,metadata,stix \
  --metadata-file ./runs/exports/artifacts/example.aggregate.metadata.json
```

Run a single adapter directly:

```bash
./scripts/hanna man \
  --module ua_phone \
  --target "Phone pivot" \
  --phones "+380991234567"
```

## GetContact / ua_phone

GetContact is wired through the `ua_phone` adapter, not as a separate module name.

The live `ua_phone` flow can use:

- `GETCONTACT_TOKEN`
- `GETCONTACT_AES_KEY`
- `TELEGRAM_BOT_TOKEN`

Without those values, `ua_phone` still runs, but it falls back to passive or manual-follow-up behavior instead of full live enrichment.

Check the live prerequisites explicitly with:

```bash
./scripts/hanna pf --modules ua_phone
```

Clean runtime state while preserving selected outputs:

```bash
./scripts/hanna rs --confirm --keep-reports
```

## Report Modes

HTML dossier rendering supports three redaction modes:

- `internal` — keeps raw values for trusted internal use
- `shareable` — default mode, masks sensitive values while keeping analytical utility
- `strict` — strongest masking for broader sharing

When `chain` exports ZIP artifacts, the ZIP carries the rendered dossier that matches the selected `report_mode`, and the manifest records that redaction mode.

## Export Surface

The machine-readable export layer supports:

- `json` — serialized `RunResult` envelope
- `metadata` — run-level metadata JSON for automation, timings, errors, counters, and generated artifact paths
- `stix` — STIX-like bundle for downstream systems
- `zip` — evidence pack containing JSON, STIX, manifest, and the rendered chain dossier when available

Example:

```bash
./scripts/hanna ch \
  --target "Example Target" \
  --report-mode strict \
  --export-formats metadata,zip \
  --metadata-file ./runs/exports/artifacts/example.chain.metadata.json \
  --export-dir ./runs/exports/artifacts
```

For shell orchestration, `list` and `reset` also support JSON-only output:

```bash
./scripts/hanna ls --json-only --output-file ./runs/exports/inventory.json
./scripts/hanna rs --confirm --json-only --output-file ./runs/exports/reset-result.json
```

## Launch Discipline

Before a controlled rollout, run the bundled pre-launch workflow:

```bash
./scripts/prelaunch_check.sh
```

For a longer operational rehearsal that includes the no-credential chain smoke:

```bash
HANNA_RUN_LIVE_SMOKE=1 ./scripts/prelaunch_check.sh
```

See [docs/LAUNCH_RUNBOOK.md](docs/LAUNCH_RUNBOOK.md) for the rollout order and pass criteria.
See [docs/RESET_RECOVERY_RUNBOOK.md](docs/RESET_RECOVERY_RUNBOOK.md) for post-launch cleanup and recovery procedures.
See [docs/PRELAUNCH_SUMMARY_SCHEMA.md](docs/PRELAUNCH_SUMMARY_SCHEMA.md) for the `final-summary.json` contract and CI gate usage.

CI-friendly prelaunch gate entrypoints:

```bash
./scripts/prelaunch_gate.sh .cache/prelaunch/<timestamp>/final-summary.json
make prelaunch-gate SUMMARY=.cache/prelaunch/<timestamp>/final-summary.json
make prelaunch-gate SUMMARY=.cache/prelaunch/<timestamp>/final-summary.json ARGS='--require-check full_rollout_rehearsal'
```

## External Tooling Policy

- ProjectDiscovery-style tools such as `httpx`, `nuclei`, `katana`, and `naabu` are expected as real binaries in `PATH` or via explicit `*_BIN` overrides.
- Fragile tools such as `blackbird`, `recon-ng`, `metagoofil`, and `EyeWitness` should be treated as explicit local checkouts or absolute binary paths.
- Internet-search tools and APIs such as Shodan or Censys should be integrated via stable credentials and scoped operational presets.

## What This Repository Is Not

This repository is not just a loose collection of OSINT scripts.

It is the orchestration layer that:

- runs adapters behind a shared contract,
- fuses heterogeneous findings into a single observable model,
- resolves entities and corroborates signals,
- renders operator dossiers,
- exports artifacts for downstream systems.

## Next Work

Core Migration Gate 2: see [docs/GATE2_EXECUTION_PLAN.md](docs/GATE2_EXECUTION_PLAN.md).

<<<<<<< docs/gate2-execution-plan
=======
Gate 2 Step 1 status: auth and adapter route contracts are stabilized with deterministic 401/403/404 outcomes.

>>>>>>> master
The next wave is focused on expanding adapter coverage and tightening release discipline:

- integrate the ProjectDiscovery stack as first-class adapters,
- add more person and infrastructure enrichment modules,
- align operational docs and presets with real-world runbooks,
- keep hardening export, report, and cleanup contracts.
