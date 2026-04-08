# Deep Audit And Finalization Plan (2026-04-08)

This document is the freeze-point before pause and is written in the requested strict format.

## A. Token & Budget Strategy

- Estimated remaining context budget: medium and sufficient for audit + execution handoff.
- Planned max spend for this audit: focus on runtime-critical paths, not broad stylistic review.
- Reserved budget for execution follow-up: kept for tomorrow handoff actions and release tasks.
- Compression strategy:
   - Use currently verified repository state and recent regression evidence.
   - Prioritize behavior and failure risk over broad code style comments.
   - Mark missing runtime evidence as `UNKNOWN` explicitly.

## B. Executive Verdict

- Current state:
   - System is operational and materially improved from earlier monolith state.
   - Decomposition already exists (`adapters/`, `pipelines/`, `runners/`, TUI split, exporters, preflight gates).
   - Test posture is solid for current surface (recent full run: 145 passed).
- Main risk (Symptom -> Cause -> Class -> Risk -> Priority):
   - Symptom: Release workflow can still break due to external-tool drift and inconsistent local tooling states.
   - Cause: Heavy dependency on third-party binaries, mixed install channels, and mutable operator environments.
   - Class: Operational reliability / release governance risk.
   - Risk: Green CI and local tests do not guarantee consistent field execution for all adapters.
   - Priority: P0 for release hardening, P1 for architecture cleanup.
- Can this be completed without full rewrite:
   - Yes. ROI is high for incremental stabilization and boundary hardening; rewrite is unnecessary and likely regressive.

## C. System Audit (Strict 10-Point Order)

### 1) Architectural Debt

- Finding:
   - Core architecture is no longer pure Big Ball of Mud, but legacy gravity remains (`deep_recon.py`, `discovery_engine.py` still large and behavior-dense).
   - Parallel model layers exist (`src/pydantic_models.py` and `src/schemas/pydantic_models.py`) and can diverge.
- Severity & Risk:
   - High: latent coupling and contract drift risk under rapid feature additions.
- Recommendation:
   - Establish one canonical contract module and deprecate duplicate schema sources.
   - Continue splitting long behavioral methods into boundary-owned components.

### 2) Reliability / Failure Modes

- Finding:
   - External adapters remain primary failure vector (timeouts, binary absence, upstream limits).
   - Wrapper and timeout handling improved, but reliability still depends on toolchain consistency.
- Severity & Risk:
   - High: partial adapter failures may silently degrade signal quality if operators ignore warnings.
- Recommendation:
   - Add per-adapter health status in run metadata (hard fail, soft fail, skipped, timed out).
   - Enforce stricter fail-policy in `--strict` modes for critical presets.

### 3) Data Integrity

- Finding:
   - Export paths and report modes are explicit and tested, but cross-run evidence consistency is sensitive to partial module failures.
   - `UNKNOWN`: full STIX semantic compliance level was not re-verified in this pass.
- Severity & Risk:
   - Medium: inconsistent evidence packs when some adapters fail late in the chain.
- Recommendation:
   - Enforce manifest completeness checks: explicit list of attempted/succeeded/failed modules per artifact.
   - Add schema-validation gate for metadata and STIX in release pipeline.

### 4) Boundaries / Dependencies

- Finding:
   - Boundaries are much better than prior baseline: adapters and runners are isolated by package.
   - Remaining boundary weakness is external binary orchestration and environment coupling.
- Severity & Risk:
   - Medium.
- Recommendation:
   - Keep adapter I/O contracts strict and centralized.
   - Add capability probing in preflight per preset and per lane.

### 5) Hotspots / Change Coupling

- Finding:
   - Highest-risk change hotspots: `src/deep_recon.py`, `src/discovery_engine.py`, `src/tui/screens.py`, `src/cli.py`, and registry/preset wiring.
- Severity & Risk:
   - High: frequent co-changes can regress behavior across orchestration + rendering + docs.
- Recommendation:
   - Protect hotspots with targeted contract tests (CLI, run metadata, TUI state rendering, export envelope).

### 6) Contracts Between Modules

- Finding:
   - Good progress in normalized envelopes and exporters.
   - `UNKNOWN`: full runtime equivalence between all legacy entry points and canonical CLI across all presets not exhaustively re-executed this pass.
- Severity & Risk:
   - Medium.
- Recommendation:
   - Add a single contract matrix test that runs canonical and legacy paths against a deterministic fixture set.

### 7) Performance / Latency

- Finding:
   - Parallel orchestration exists; runtime remains bounded by slow external adapters and network uncertainty.
   - TUI and report rendering acceptable for current scale.
- Severity & Risk:
   - Medium.
- Recommendation:
   - Track per-adapter wall-clock and timeout ratios in metadata and preflight summaries.
   - Add operator presets optimized for speed vs depth.

### 8) Security (OPSEC)

- Finding:
   - Prior secret handling incident confirms operational risk from human workflow, not only code.
   - Token management can be compromised if secrets are shared outside secure channels.
   - `UNKNOWN`: full DNS leak/traffic-routing guarantees for every adapter path were not revalidated in this pass.
- Severity & Risk:
   - Critical for production use.
- Recommendation:
   - Enforce strict secret hygiene: rotate compromised credentials immediately, never share tokens in chats, isolate `.env`, and require preflight secret checks.
   - Add explicit OPSEC preflight assertions for proxy-required modes.

### 9) Testability / Operability

- Finding:
   - Test suite is active and broad compared to previous baseline.
   - Operational scripts (`prelaunch`, `gate`, `reset`) are present and documented.
- Severity & Risk:
   - Medium.
- Recommendation:
   - Promote smoke runs for critical presets into CI with deterministic no-secret fixtures.
   - Keep post-run summaries as machine-readable release evidence.

### 10) Smells & Antipatterns

- Finding:
   - Residual long-method density and mixed responsibility in some core files.
   - Documentation and launch pathways are much cleaner than before.
- Severity & Risk:
   - Medium.
- Recommendation:
   - Continue surgical extraction with behavior-lock tests.
   - Avoid broad rewrites during release phase.

## D. Machine-to-Human Code Refactor Doctrine

- Where code is still machine-like:
   - Behavior-heavy core modules with mixed orchestration, transformation, and reporting concerns.
   - Duplicate schema representations that can drift.
- Convert to engineering-grade:
   - One owner per boundary: orchestration, extraction, verification, export, and UI each with explicit contracts.
   - Every external adapter must return a normalized envelope with typed status and reason codes.
- Abstractions to remove:
   - Parallel or duplicate model layers that are not the runtime source of truth.
   - Ad-hoc fallback paths that bypass canonical runners without explicit compatibility tests.
- Hard prohibitions for future PRs:
   - No new adapter without contract test + preflight visibility.
   - No secret-handling changes without rotation/revocation procedure updates.
   - No large multi-concern edits to hotspot files without targeted regression additions.

## E. Canonical Execution Plan (Finalization)

### Phase 0: Freeze And Evidence Capture (now)

- Goal: freeze reproducible baseline before pause.
- Tasks:
   - Keep this audit as release checkpoint artifact.
   - Preserve current git state and reference commit.
- Dependencies: none.
- Expected output: frozen audit + plan + checkpoint note.
- Acceptance criteria: committed and pushed checkpoint files.

### Phase 1: Release Hardening (P0)

- Goal: remove release-time operational uncertainty.
- Tasks:
   - Enforce strict preflight matrix per critical preset.
   - Normalize external binary resolution and explicit override documentation.
   - Add fail-policy controls for adapter timeout/error classes.
- Dependencies: current adapter wrappers and preflight scripts.
- Expected output: deterministic pass/fail gate before chain runs.
- Acceptance criteria: preflight gate blocks unsafe launch paths reliably.

### Phase 2: Contract Consolidation (P1)

- Goal: eliminate drift between runtime data contracts.
- Tasks:
   - Select one canonical contract module.
   - Remove/deprecate duplicate schema definitions.
   - Add contract parity tests for canonical vs compatibility entry points.
- Dependencies: test suite and exporter contracts.
- Expected output: single source of truth for envelopes and schema checks.
- Acceptance criteria: no duplicated runtime contract owners.

### Phase 3: Hotspot Surgical Refactor (P1)

- Goal: lower blast radius of high-change modules.
- Tasks:
   - Extract remaining large methods from `deep_recon.py` and `discovery_engine.py` by responsibility.
   - Add micro-regression tests for extracted behavior.
- Dependencies: Phases 1-2 complete.
- Expected output: smaller units with stable behavior.
- Acceptance criteria: unchanged public behavior, improved maintainability metrics.

### Phase 4: Operational Maturity (P2)

- Goal: improve observability and operator confidence.
- Tasks:
   - Add adapter-level telemetry (wall time, timeout class, degradation cause).
   - Tighten runbook workflows for incident response and credential rotation.
- Dependencies: stable core release.
- Expected output: faster diagnosis, lower MTTR.
- Acceptance criteria: actionable post-run summaries and clear rollback paths.

## F. Task Graph For Cheaper Model

1. Scope: preflight strictness and binary checks.
    - Touch: `scripts/prelaunch_check.sh`, `scripts/prelaunch_gate.sh`, `docs/LAUNCH_RUNBOOK.md`.
    - Do not touch: core adapter behavior.
    - Expected diff: stricter gate conditions and documented fail reasons.
    - Stop criterion: all critical presets produce deterministic gate result.

2. Scope: contract unification.
    - Touch: `src/pydantic_models.py` or `src/schemas/pydantic_models.py` (one selected owner), import sites.
    - Do not touch: TUI visual layer.
    - Expected diff: removed duplication, updated imports, passing contract tests.
    - Stop criterion: single runtime contract owner exists.

3. Scope: adapter status normalization.
    - Touch: `src/adapters/*`, `src/worker.py`, exporter metadata surface.
    - Do not touch: dossier styling.
    - Expected diff: uniform status/reason envelope.
    - Stop criterion: all adapters map to same status taxonomy.

4. Scope: hotspot extraction pass #1.
    - Touch: `src/deep_recon.py`, `src/discovery_engine.py`, new helper modules.
    - Do not touch: external behavior contracts.
    - Expected diff: smaller functions, no behavior change.
    - Stop criterion: regression tests unchanged and passing.

5. Scope: observability and handoff.
    - Touch: metadata exporters, runbooks.
    - Do not touch: adapter API signatures unless required.
    - Expected diff: clearer post-run diagnostics and operator checklists.
    - Stop criterion: incident triage can be done from artifacts only.

## G. Definition Of Done & Control Checklist

- Stability indicators for 14+ modules under load:
   - No unexpected process crashes in orchestrator.
   - Controlled timeout behavior per adapter with explicit reason codes.
   - Export manifest always includes attempted/success/failed module matrix.
   - Chain completion remains deterministic under strict preflight.
   - Redaction mode and report/export parity verified.

- Pre-release checklist:
   - Preflight strict gate passes for target preset matrix.
   - Full regression suite passes.
   - Secret hygiene validated (rotated, not exposed, not committed).
   - Runbooks updated for current commands and failure signatures.
   - Compatibility path checks (legacy entry points) pass on deterministic fixtures.
   - Release checkpoint committed and pushed.

## Freeze Note For Tomorrow

- This document is the authoritative checkpoint before pause.
- Pending items at freeze:
   - `.gitmodules` addition for normalized tool submodules.
   - Possible local dirt inside submodules (operator-local and not part of superproject source code).
