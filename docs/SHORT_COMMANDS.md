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

## No-Key Smoke Test

Use this when you want to verify the orchestration path without relying on paid APIs or missing secrets.

```bash
./scripts/test_no_keys.sh
./scripts/test_no_keys.sh example.com
```

The script uses the minimal autonomous preset `core-local` and runs `aggregate` instead of `chain` to avoid deep-recon blocking.
Core completion must not depend on APIs, external services, slow modules, or enrichment layers.

Artifacts are written to `./.cache/no-key-smoke/`:

```bash
open ./.cache/no-key-smoke/no-key-smoke.html
cat ./.cache/no-key-smoke/no-key-smoke.metadata.json
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

## Reference Dashboard

Reference layout is now exposed as native repo commands and shell aliases.

```bash
source scripts/hanna-aliases.sh
hdash
hlayout-ref
hfocus-graph
```

Layout intent:

| Area | Command | Purpose |
|---|---|---|
| Top bar | `npm run topbar` | One-line health, throughput, memory, cache, queue |
| Metrics tree | `npm run tui:tree` | Fast/slow lane snapshot + risk line |
| Graph | `npm run tui:graph` | Throughput and latency sparkline |
| Controls | `npm run tui:controls` | Parse / Export / Reset / Config cheat sheet |
| Logs | `npm run logs:live` | Live runtime logs |

Available layouts:

| Alias | Layout |
|---|---|
| `hlayout-ref` | Reference proportions: top + metrics + graph + controls + logs |
| `hlayout1` | Compact tiled |
| `hlayout2` | Wide main-vertical |
| `hlayout3` | Mobile even-horizontal |

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
| `phone <target>` | Manual `ua_phone` pivot |
| `fop <target>` | Manual `opendatabot` pivot |
| `leak <target>` | Manual `ua_leak` pivot |
| `email <target>` | Manual `holehe` pivot |
| `ashok <target>` | Manual `ashok` deep infra pivot |
| `soc <target>` | Manual `social_analyzer` pivot |
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
phone +380501234567
fop +380501234567
leak user@example.com
email target@example.org
ashok example.com
soc @handle
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
source scripts/hanna-aliases.sh
hdash
hlayout-ref
hfocus-graph
```

## Environment Readiness

The repository already contains a local `.env`. Validate the current setup with:

```bash
./scripts/hanna pf
./scripts/hanna pf --modules ua_phone
./scripts/hanna pf --modules ua_phone --json-only
```

## OPSEC Routing

Canonical safe routing rules are documented in `docs/OPSEC_RUNBOOK.md`.

Quick reference:

```bash
./scripts/hanna agg --target example.com --modules pd-infra --tor
./scripts/hanna ch --target example.com --modules full-spectrum --proxy socks5h://127.0.0.1:9055
HANNA_REQUIRE_PROXY=1 ./scripts/hanna ui --tor --plain
```