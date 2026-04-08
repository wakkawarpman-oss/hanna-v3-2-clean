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

## NPM Shortcuts

Quick aliases added directly to `package.json`:

| Command | Equivalent | Time |
|---|---|---|
| `npm run h` | `system-verify` | ~3s |
| `npm run go` | `production-readiness` (verify + master-test) | ~8s |
| `npm run live` | `master-test` | ~5s |
| `npm run reset` | `hanna reset --confirm --json-only` | ~1s |
| `npm run bench` | `benchmark:multi` | ~15s |

## Shell Aliases

Load once per shell session:

```bash
source scripts/hanna-aliases.sh
```

### OSINT Workflow Aliases

| Alias | Purpose |
|---|---|
| `hls` | List modules and presets |
| `hpf` | Preflight check |
| `hui` | TUI dashboard (plain mode) |
| `hagg` | Parallel adapter run |
| `hch` | Full pipeline (chain) |
| `hman` | Single adapter run |
| `hfs <target>` | Full-spectrum aggregate |
| `hchainfs <target>` | Full-spectrum chain |
| `hsum <target> <text>` | Smart summary + risk flags |

### Quick Operations Aliases

| Alias | Purpose |
|---|---|
| `hanna` | `cd` to repo + `system-verify` |
| `hstart` | `npm start` |
| `hstop` | Stop via pm2 / systemctl |
| `hlogs` | `tail -f` on log directory |
| `hhealth` | `curl` health endpoint + JSON pretty-print |
| `hreset` | Factory reset (JSON output) |

### Example Usage

```bash
hls
hpf --modules full-spectrum
hui --target "Ivan" --modules full-spectrum
hfs example.com
hchainfs "Ivan" --verify --export-formats json,metadata,stix,zip
hman --module nuclei --target https://example.com
hsum "Case Target" "password dump for user@example.com near військова частина"
```

### Quick Operations

```bash
hanna          # Verify everything
hstart         # Launch server
hlogs          # Live log tail
hhealth        # API health check
hreset         # Factory reset
hstop          # Stop all processes
```

## tmux Dashboard (Production)

```bash
tmux new -s hanna -d
tmux split-window -h "watch -n 5 npm run h"
tmux split-window -v "source scripts/hanna-aliases.sh && hlogs"
tmux split-window -v "watch -n 30 curl -s localhost:3000/health"
tmux attach -t hanna
```

## Environment Readiness

The repository already contains a local `.env`. Validate the current setup with:

```bash
./scripts/hanna pf
./scripts/hanna pf --modules ua_phone
./scripts/hanna pf --modules ua_phone --json-only
```