# Post-Audit Report (2026-04-08)

## Scope
- Validate agreed adapter expansion is integrated end-to-end.
- Run regression tests.
- Run smoke checks for Phase 1 adapters.
- Verify external tool availability in runtime PATH.

## Implementation Status
- Adapter package contains all agreed modules (28 total in registry).
- Registry and presets include: pd-infra, pd-full, person-deep, email-chain, subdomain-full, port-scan, infra-deep, recon-auto, full-spectrum-2026.
- CLI exposes all adapters and presets.

## Code Changes Completed In This Audit
1. Improved CLI binary resolution for adapters:
   - Added PATH augmentation with common user-level bin directories.
   - Added executable resolution via shutil.which on the augmented PATH.
   - File: src/adapters/cli_common.py
2. Improved timeout handling for CLI wrappers:
   - On timeout, return a synthetic CompletedProcess with returncode 124.
   - Prevents false classification of timeout as missing binary.
   - File: src/adapters/cli_common.py
3. Hardened Nuclei adapter startup path:
   - Added -duc to disable update checks during scans.
   - Added explicit timeout warning path.
   - File: src/adapters/nuclei.py

## Validation Evidence
### Automated tests
- Command: pytest -q
- Result: 46 passed, 0 failed.

### CLI registry visibility
- Command: python3 src/cli.py list
- Result: All planned modules and presets visible.

### Phase 1 smoke checks
- httpx_probe: PASS (2 hits on example.com)
- naabu: PASS (8 hits on example.com)
- katana: PASS (1 hit on https://example.com)
- nuclei: EXECUTES but times out at wrapper timeout window on https://example.com in this environment.

## Findings (ordered by severity)
1. HIGH: Tool install method mismatch in original plan for several tools.
   - recon-ng and metagoofil are not installable from PyPI as written.
   - blackbird package on PyPI resolves to an outdated package chain failing on modern Python due logilab-astng/2to3 dependency.
2. MEDIUM: Nuclei scans can exceed wrapper timeout under some network/template conditions.
   - Adapter now reports timeout explicitly; operational tuning still recommended.
3. LOW: Some adapters depend on third-party binaries that may exist outside default PATH.
   - Mitigated by PATH augmentation in adapter runner.

## Remaining Operational Actions
1. Use supported install channels for missing tools (official repos/package managers).
2. Set explicit binary overrides in .env for non-standard installations:
   - NUCLEI_BIN, KATANA_BIN, NAABU_BIN, BLACKBIRD_BIN, RECONNG_BIN, METAGOOFIL_BIN, EYEWITNESS_BIN.
3. Consider per-adapter timeout knobs for long-running scans (especially nuclei).

## Release Readiness Verdict
- Code integration: READY.
- Test suite: GREEN.
- Runtime dependencies: PARTIALLY READY (depends on operator-side installation of non-PyPI tools).
