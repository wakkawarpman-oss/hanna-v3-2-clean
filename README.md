# HANNA v3.2 Clean

HANNA is a modular OSINT orchestration platform for running adapter-based collection, normalizing observables, resolving entities, and producing both operator-facing dossiers and machine-readable exports.

This repository is the clean canonical codebase published as `wakkawarpman-oss/hanna-v3-2-clean`.

## Current Status

The project is in late integration and release hardening.

Core platform capabilities are already present:

- Canonical CLI for `chain`, `aggregate`, `manual`, `preflight`, `list`, and `reset`
- Discovery engine with ingestion, observable registration, entity resolution, and verification flows
- Safe-by-default HTML dossier generation with `internal`, `shareable`, and `strict` redaction modes
- Canonical export surface for JSON, STIX-like bundles, and ZIP evidence packs
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 src/cli.py preflight
```

Use strict preflight before operational runs:

```bash
python3 src/cli.py preflight --strict
```

## Main Workflows

Run the full discovery pipeline and render a sanitized dossier:

```bash
python3 src/cli.py chain \
  --target "Example Target" \
  --modules ua_leak,ghunt,opendatabot \
  --verify \
  --report-mode shareable \
  --export-formats json,stix,zip
```

Run selected adapters in parallel without dossier rendering:

```bash
python3 src/cli.py aggregate \
  --target example.com \
  --modules full-spectrum \
  --workers 4 \
  --export-formats json,stix
```

Run a single adapter directly:

```bash
python3 src/cli.py manual \
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
python3 src/cli.py preflight --modules ua_phone
```

Clean runtime state while preserving selected outputs:

```bash
python3 src/cli.py reset --confirm --keep-reports
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
- `stix` — STIX-like bundle for downstream systems
- `zip` — evidence pack containing JSON, STIX, manifest, and the rendered chain dossier when available

Example:

```bash
python3 src/cli.py chain \
  --target "Example Target" \
  --report-mode strict \
  --export-formats zip \
  --export-dir ./runs/exports/artifacts
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

The next wave is focused on expanding adapter coverage and tightening release discipline:

- integrate the ProjectDiscovery stack as first-class adapters,
- add more person and infrastructure enrichment modules,
- align operational docs and presets with real-world runbooks,
- keep hardening export, report, and cleanup contracts.
