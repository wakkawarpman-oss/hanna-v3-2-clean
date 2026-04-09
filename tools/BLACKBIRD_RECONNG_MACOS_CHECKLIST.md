# HANNA macOS checklist: blackbird + recon-ng

This checklist is aligned to the HANNA repo layout and current preflight logic in `src/preflight.py`.

Expected repo-local paths:

- `tools/blackbird/blackbird.py`
- `tools/blackbird/.venv/bin/python`
- `tools/recon-ng/recon-ng`
- `tools/recon-ng/.venv/bin/python`

Current state on this workspace:

- `tools/blackbird/` exists but is empty
- `tools/recon-ng/` exists but is empty

## 1. Blackbird

Clone into the repo-local tool path:

```bash
cd '/Users/admin/Desktop/runs/exports/html/dossiers/new osint-ui rewrite/hanna-v3-2-clean'
rm -rf tools/blackbird
git clone https://github.com/p1ngul1n0/blackbird.git tools/blackbird
python3 -m venv tools/blackbird/.venv
source tools/blackbird/.venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r tools/blackbird/requirements.txt
deactivate
```

Smoke checks:

```bash
test -f tools/blackbird/blackbird.py
test -x tools/blackbird/.venv/bin/python
tools/blackbird/.venv/bin/python tools/blackbird/blackbird.py --help | head -n 20
```

Optional explicit env override for HANNA:

```bash
export BLACKBIRD_BIN='tools/blackbird/.venv/bin/python'
```

If you use `BLACKBIRD_BIN`, HANNA expects the executable to be directly runnable. For the current adapter implementation, repo-local checkout is the safest path because it auto-detects both `blackbird.py` and `.venv/bin/python`.

## 2. recon-ng

Clone into the repo-local tool path:

```bash
cd '/Users/admin/Desktop/runs/exports/html/dossiers/new osint-ui rewrite/hanna-v3-2-clean'
rm -rf tools/recon-ng
git clone https://github.com/lanmaster53/recon-ng.git tools/recon-ng
python3 -m venv tools/recon-ng/.venv
source tools/recon-ng/.venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r tools/recon-ng/REQUIREMENTS
deactivate
chmod +x tools/recon-ng/recon-ng
```

Smoke checks:

```bash
test -f tools/recon-ng/recon-ng
test -x tools/recon-ng/.venv/bin/python
tools/recon-ng/.venv/bin/python tools/recon-ng/recon-ng --help | head -n 20
```

Optional PATH bridge if you want preflight to resolve `recon-ng` directly:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf '/Users/admin/Desktop/runs/exports/html/dossiers/new osint-ui rewrite/hanna-v3-2-clean/tools/recon-ng/recon-ng' "$HOME/.local/bin/recon-ng"
chmod +x "$HOME/.local/bin/recon-ng"
```

## 3. Preflight verification

Run scoped checks after both installs:

```bash
cd '/Users/admin/Desktop/runs/exports/html/dossiers/new osint-ui rewrite/hanna-v3-2-clean'
./scripts/hanna preflight --modules blackbird,reconng --json-summary-only
```

Expected result:

- `blackbird.status = ok`
- `reconng.status = ok`

## 4. Full-chain verification

After install, re-test the affected modules explicitly:

```bash
cd '/Users/admin/Desktop/runs/exports/html/dossiers/new osint-ui rewrite/hanna-v3-2-clean'
HIBP_API_KEY=00000000000000000000000000000000 \
HANNA_RUNS_ROOT='/Users/admin/Desktop/ОСІНТ_ВИВІД/runs' \
./scripts/hanna chain \
  --target 'account-exists@hibp-integration-tests.com' \
  --phones '+380991234598' \
  --usernames 'account-exists' \
  --modules full-spectrum \
  --no-preflight \
  --json-summary-only
```

## 5. Failure signatures to watch

If `blackbird` still fails:

- check that `tools/blackbird/blackbird.py` exists
- check that `tools/blackbird/.venv/bin/python` exists
- run the smoke command directly inside the repo root

If `recon-ng` still fails:

- check that `tools/recon-ng/recon-ng` exists
- check that it is executable
- check that `tools/recon-ng/.venv/bin/python` exists
- run `tools/recon-ng/.venv/bin/python tools/recon-ng/recon-ng --help`

If preflight still shows `missing repo checkout and PATH binary`, the repo-local layout does not match what `src/preflight.py` expects.