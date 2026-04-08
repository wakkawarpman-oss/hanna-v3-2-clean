# HANNA Reset and Recovery Runbook

This runbook is for post-launch incidents where operators must clean, preserve, or recover runtime state without guessing.

## 1. When to Use This

Use this document when one of the following happens:

1. generated artifacts are corrupted or incomplete;
2. runtime directories grow unexpectedly;
3. operators need a clean rerun without deleting everything blindly;
4. a failed rollout leaves stale DB, logs, or dossier artifacts behind.

## 2. First Triage

Before any cleanup, capture the current state:

```bash
cd /Users/admin/Desktop/hanna-v3-2-clean
./scripts/hanna pf --modules full-spectrum --json-only > ./runs/exports/preflight.recovery.json
./scripts/hanna ls --json-only --output-file ./runs/exports/inventory.recovery.json
```

If the problem concerns a specific run, copy or archive these first:

1. exported ZIP bundles;
2. HTML dossiers;
3. metadata JSON;
4. raw logs under the active runs root.

## 3. Safe Cleanup Levels

### Level 1: Remove DB only

Use when entity state is stale, but logs and artifacts must remain.

```bash
./scripts/hanna rs --confirm --keep-logs --keep-reports --keep-artifacts
```

### Level 2: Remove DB and logs, keep reports and exports

Use when runtime execution is noisy, but generated evidence packs must remain reviewable.

```bash
./scripts/hanna rs --confirm --keep-reports --keep-artifacts
```

### Level 3: Remove DB, logs, and reports, keep exported artifacts

Use when dossier rendering must be regenerated, but export bundles should stay archived.

```bash
./scripts/hanna rs --confirm --keep-artifacts
```

### Level 4: Full generated-state reset

Use only when you intentionally want a full clean rerun.

```bash
./scripts/hanna rs --confirm
```

## 4. Machine-Readable Reset Output

For incident logging and operator handoff, always prefer JSON output:

```bash
./scripts/hanna rs --confirm --json-only --output-file ./runs/exports/reset-result.json
```

This gives a concrete list of `removed` and `missing` paths.

## 5. Recovery After Reset

After cleanup:

1. rerun `./scripts/hanna pf --modules <preset>`;
2. rerun `./scripts/prelaunch_check.sh` if the system is preparing for release or re-entry into production;
3. only then restart operator workflows.

## 6. Do Not Do This

Do not use ad hoc deletion during incidents:

1. do not `rm -rf` the runs tree manually unless the reset command is itself broken;
2. do not delete exported evidence before archiving it;
3. do not reset the environment before capturing preflight and affected metadata.

## 7. Escalation Conditions

Escalate instead of resetting repeatedly if any of these are true:

1. `worker_crash` rises across multiple runs after a clean reset;
2. ZIP bundles are still incomplete after a rerun;
3. preflight turns red on tools that were green at release freeze;
4. the same adapter repeatedly produces stale or contradictory metadata after DB cleanup.