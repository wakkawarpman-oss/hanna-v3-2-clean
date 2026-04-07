# HANNA v3.2 Clean Repository

Clean standalone repository for running HANNA deep recon, discovery fusion, and HTML dossier generation.

## What Is Included

- `src/deep_recon.py` — multi-adapter recon runner (presets, lanes, module orchestration)
- `src/discovery_engine.py` — ingestion, entity resolution, correlation, report graph
- `src/run_discovery.py` — main CLI with single-target and batch mode (`--targets-file`)
- `src/bridge_legacy_phone_dossier.py` — legacy bridge dossier renderer
- `src/pydantic_models.py` — structured models used by the pipeline
- `requirements.txt` — Python dependencies
- `examples/` — ready-to-use sample files for batch logic
- `docs/` — architecture and batch format docs

## Quick Start

```bash
cd HANNA_v3_2_clean_repo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 src/cli.py preflight
```

## External Tooling Policy

- Go tools such as `nuclei`, `katana`, and `naabu` are expected as real binaries in `PATH` or via explicit `*_BIN` env overrides.
- Fragile tools such as `blackbird`, `recon-ng`, `metagoofil`, and `EyeWitness` should be treated as repo-local checkouts under `tools/` or pointed to with explicit absolute `*_BIN` env vars.
- Do not assume `pip install recon-ng`, `pip install metagoofil`, or `pip install blackbird` are reliable production install paths on modern macOS/Python.

Run preflight before operational use:

```bash
python3 src/cli.py preflight --strict
```

Scope preflight to selected modules or presets:

```bash
python3 src/cli.py preflight --modules pd-infra --strict
```

`aggregate` and `chain` now run preflight fail-fast by default. Use `--no-preflight` only for deliberate troubleshooting.

## Single Target Run

```bash
python src/run_discovery.py \
  --target "Example Target" \
  --mode fast-lane \
  --verify \
  --output ./runs/exports/html/dossiers/example_fast.html
```

## Batch Run (Array of Targets)

```bash
python src/run_discovery.py \
  --targets-file examples/targets.txt \
  --mode fast-lane \
  --verify \
  --output ./runs/exports/html/dossiers/batch_fast.html
```

`--targets-file` format:

```text
target|phone1,phone2|username1,username2
```

Example file is available at `examples/targets.txt`.

## Folder Intake (TXT/PDF/CSV -> Full HTML Dossier)

Drop your evidence files into a folder and run:

```bash
python src/intake_drop_folder.py \
  --input-dir /path/to/drop_folder \
  --target "Case Target" \
  --profile username \
  --mode fast-lane \
  --verify
```

What it does:

- Recursively finds `txt`, `pdf`, `csv`
- Extracts text into normalized intake logs
- Generates metadata JSON files in exports
- Runs discovery + deep recon
- Builds a full HTML dossier

Use `--no-build-dossier` if you only want ingestion.

## Outputs

- Deep recon JSON reports: `~/Desktop/ОСІНТ_ВИВІД/runs/deep_recon_*.json`
- HTML dossier output path is controlled by `--output`
- Discovery DB default: `~/Desktop/ОСІНТ_ВИВІД/runs/discovery.db`

## Timeout Model

- Request timeout is capped inside adapters.
- CLI subprocess timeout is bounded below the worker hard timeout with a safety margin.
- Long-running modules such as `nuclei`, `reconng`, `metagoofil`, and `eyewitness` use module-specific worker timeout overrides.

## Nuclei Profiles

- `quick` is the default operator profile and is intended for validation, smoke checks, and lighter infra presets.
- `deep` expands target count and nuclei scan pressure for heavier infrastructure runs.
- Set explicitly with `--nuclei-profile quick|deep` or via `HANNA_NUCLEI_PROFILE`.
- Presets such as `pd-infra` and `recon-auto` infer `quick`; `pd-full`, `infra-deep`, and `full-spectrum-2026` infer `deep` unless overridden.

## Checkpoint Saved

Checkpoint archive from source state:

`~/Desktop/ОСІНТ_ВИВІД/runs/checkpoints/hanna_specs_checkpoint_20260406_163813.tar.gz`
