# HANNA Short Commands

This file documents the shortest supported commands for day-to-day terminal use.

## Direct Wrapper

Use the repo-local launcher so you do not need to set `PYTHONPATH` manually.

```bash
cd /Users/admin/Desktop/hanna-v3-2-clean
./scripts/setup_hanna.sh
./scripts/hanna ls
```

`./scripts/hanna` is the canonical operator entrypoint.
`python3 src/run_discovery.py` remains available only for legacy compatibility.

## Short CLI Subcommands

These are built into `src/cli.py` and work both through `./scripts/hanna` and direct Python execution.

| Short | Full | Purpose |
|---|---|---|
| `ls` | `list` | List modules and presets |
| `pf` | `preflight` | Check binaries, env vars, runtime prerequisites |
| `ui` | `tui` | Launch terminal dashboard |
| `agg` | `aggregate` | Parallel adapter run |
| `ch` | `chain` | Full pipeline |
| `man` | `manual` | Single adapter run |
| `sum` | `summarize` | Smart summary + risk flags |
| `rs` | `reset` | Factory reset for runtime state |

## Recommended User Commands

```bash
./scripts/hanna ls
./scripts/hanna ls --json-only --output-file ./runs/exports/inventory.json
./scripts/hanna pf --modules full-spectrum
./scripts/hanna pf --modules ua_phone --json-only
./scripts/hanna ui --target "Ivan" --modules full-spectrum
./scripts/hanna agg --target example.com --modules full-spectrum --metadata-file ./runs/exports/artifacts/example.aggregate.metadata.json
./scripts/hanna ch --target "Ivan" --modules full-spectrum --verify --export-formats json,metadata,stix,zip --metadata-file ./runs/exports/artifacts/ivan.chain.metadata.json
./scripts/hanna man --module nuclei --target https://example.com
./scripts/hanna sum --target "Case Target" --text "password dump for user@example.com"
./scripts/hanna rs --confirm
./scripts/hanna rs --confirm --json-only --output-file ./runs/exports/reset-result.json
```

## Shell Aliases

Load once per shell session:

```bash
cd /Users/admin/Desktop/hanna-v3-2-clean
source scripts/hanna-aliases.sh
```

Then you can use these even shorter commands:

```bash
hls
hls --json-only --output-file ./runs/exports/inventory.json
hpf --modules full-spectrum
hpf --modules ua_phone --json-only
hui --target "Ivan" --modules full-spectrum
hfs example.com
hchainfs "Ivan" --verify --export-formats json,metadata,stix,zip --metadata-file ./runs/exports/artifacts/ivan.chain.metadata.json
hman --module nuclei --target https://example.com
hsum "Case Target" "password dump for user@example.com near військова частина"
```

## Environment Readiness

The repository already contains a local `.env`. Validate the current setup with:

```bash
./scripts/hanna pf
./scripts/hanna pf --modules ua_phone
./scripts/hanna pf --modules ua_phone --json-only
```