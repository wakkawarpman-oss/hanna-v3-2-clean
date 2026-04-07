# OSINT-Adapter System Audit

**Role:** Principal Engineer · Systems Auditor · Release Architect  
**Date:** 2026-04-06  
**Codebase snapshot:** `HANNA_v3_2_clean_repo/src/` (Python backend) + `ОСІНТ_ВИВІД/runs/exports/html/dossiers/` (Node.js renderer)  
**Total LoC audited:** ~10,074 Python + ~1,200 Node.js

---

## A. Token & Budget Strategy

This audit was produced after reading every line of production source code. Coverage:

| File | Lines | Read | Status |
|---|---|---|---|
| `discovery_engine.py` | 2,132 | 2,132 | FULL |
| `deep_recon.py` | 3,585 | 3,585 | FULL |
| `run_discovery.py` | 293 | 293 | FULL |
| `pydantic_models.py` | 242 | 242 | FULL |
| `bridge_legacy_phone_dossier.py` | 894 | 500 | PARTIAL — remaining 394 lines are HTML template literals for legacy dossier rendering |
| `intake_drop_folder.py` | 218 | 218 | FULL |
| Node.js pipeline (`src/`) | ~1,200 | ~1,200 | FULL (from prior implementation) |

Not read (spec-only, not runtime):
- `audit_pack/specs/api_main.py` (1,964 lines) — FastAPI control-plane, never instantiated
- `audit_pack/specs/schema.sql` (1,281 lines) — PostgreSQL with RLS, never deployed

---

## B. Executive Verdict

### Current State

OSINT-Adapter is a **working but unscalable monolith** consisting of two God Objects (`DiscoveryEngine` at 2,132 lines, `deep_recon.py` as a 3,585-line God Module), a clean but orphaned spec layer (Pydantic models, FastAPI routes, PostgreSQL schema that *nothing uses*), and a recently-hardened Node.js rendering pipeline.

The system *does* produce intelligence dossiers. It orchestrates 14 OSINT adapters via process isolation, performs entity resolution through Union-Find on SQLite, verifies social profiles with HTTP probes, and renders multi-section HTML reports. For a single-analyst CLI workflow it functions.

It is **not production-grade**. The gap between the aspirational spec (claims assessor, RLS, graph CRUD) and the actual runtime (flat SQLite, subprocess.run, hardcoded ~/Desktop paths) is severe.

### Main Risk

| Symptom | Cause | Class | Risk | Priority |
|---|---|---|---|---|
| Spec layer (Pydantic, FastAPI, PostgreSQL) exists but is never imported by the running engine | Aspirational architecture was written before the runtime; runtime grew organically without consuming the models | **Architectural schizophrenia** — two divergent architectures exist in the same repo | Developers making changes to the spec believe they're affecting runtime behavior. Any integration effort requires bridging two incompatible data models. | **P0-CRITICAL** |

### ROI of Fixing vs Rewriting

**Fix.** The engine logic is domain-correct. Entity resolution, confidence tiering, lane-based recon orchestration, and the adapter dispatch model are sound. Rewriting would discard ~12 months of OSINT domain encoding. The correct path is: (1) extract and modularize, (2) enforce the Pydantic contracts at module boundaries, (3) delete or quarantine the dead spec layer until it's wired in.

---

## C. System Audit (10-Point Analysis)

### C.1 — Architectural Debt

| # | Finding | Severity | File | Lines |
|---|---|---|---|---|
| AD-1 | **God Class: DiscoveryEngine** — ingestion, validation, extraction, entity resolution (Union-Find), profile verification (ThreadPoolExecutor), content verification, deep recon integration, statistics, and HTML rendering (600+ lines of inline CSS/HTML) in ONE class | CRITICAL | `discovery_engine.py` | 1–2132 |
| AD-2 | **God Module: deep_recon.py** — 14 adapter classes + data classes + transliteration helpers + module registry + priority matrix + worker function + orchestrator class + CLI in a single 3,585-line file | CRITICAL | `deep_recon.py` | 1–3585 |
| AD-3 | **Spec-Runtime Divergence** — `pydantic_models.py` defines `Observable`, `NormalizedEntityBundle`, `AdapterCapability`, `RetryPolicy`, `QuotaWindow` — none of which are imported by `discovery_engine.py` or `deep_recon.py`. The engine uses its own `@dataclass Observable` and `@dataclass IdentityCluster`. `requirements.txt` lists `fastapi`, `uvicorn`, `pydantic`, `asyncpg` — none used at runtime. | HIGH | `pydantic_models.py` vs `discovery_engine.py` | All |
| AD-4 | **Dead Control Plane** — `api_main.py` defines a full FastAPI app (graph CRUD, run orchestration, claims assessor with PostgreSQL) that is never started or referenced by any CLI entry point | MEDIUM | `audit_pack/specs/api_main.py` | All |
| AD-5 | **Hardcoded filesystem layout** — `~/Desktop/ОСІНТ_ВИВІД/runs/` appears in: `discovery_engine.py` (3 places), `deep_recon.py` (1 place), `intake_drop_folder.py` (default), `bridge_legacy_phone_dossier.py` (implicit via metadata paths). Also `~/Desktop/MEDIA/` in `SatIntelAdapter`. | HIGH | Multiple | Scattered |
| AD-6 | **Inline HTML rendering** — `render_graph_report()` is ~700 lines of f-string HTML/CSS concatenation inside DiscoveryEngine. `bridge_legacy_phone_dossier.py` has another ~400 lines of inline HTML. Two independent renderers with no shared template system. | MEDIUM | `discovery_engine.py:1530–2105`, `bridge_legacy_phone_dossier.py:350–750` | — |

**Recommendation:**
1. Extract DiscoveryEngine into: `ingestion.py`, `entity_resolution.py`, `verification.py`, `reporting.py`
2. Split `deep_recon.py` into `adapters/` package — one file per adapter, shared `base.py`
3. Either wire Pydantic models into the engine or delete them. The current state is a liability.
4. Replace hardcoded paths with a single `config.py` using `XDG_DATA_HOME` or env vars.

---

### C.2 — Reliability & Failure Modes

| # | Finding | Severity | File | Lines |
|---|---|---|---|---|
| RF-1 | **No retry logic in base adapter** — `ReconAdapter._fetch()` and `_post()` use raw `urllib.request.urlopen` with a single attempt. Any transient network failure (DNS timeout, TLS handshake stall, 502 upstream) kills the result. 14 adapters inherit this behavior. | HIGH | `deep_recon.py` | `_fetch()` ~120–160, `_post()` ~160–200 |
| RF-2 | **No circuit breaker** — If an external API (GetContact, Search4Faces, FIRMS) is down, every invocation retries blindly. No backoff, no health tracking, no "this service has failed N times, skip it" logic. | HIGH | `deep_recon.py` | All adapters |
| RF-3 | **Zombie subprocess risk** — `subprocess.run(..., timeout=T)` kills the *main* process but child processes spawned by Maryam/Ashok/GHunt may survive. No `preexec_fn=os.setsid` + `os.killpg()` pattern. | MEDIUM | `deep_recon.py` | MaryamAdapter, AshokAdapter, GHuntAdapter |
| RF-4 | **ProcessPoolExecutor without worker crash recovery** — If a worker segfaults (e.g., Playwright Chromium crash in WebSearchAdapter), the Future raises `BrokenProcessPool` and all remaining tasks fail. No pool rebuild logic. | MEDIUM | `deep_recon.py` | `DeepReconRunner.run()` ~3198–3380 |
| RF-5 | **Memory pressure from JSONL scanning** — `UALeakAdapter` and `RULeakAdapter` iterate up to 500,000 lines per file. With typical JSONL payloads, this can load 200–500MB into memory per worker process. With ProcessPoolExecutor and 3+ workers, total memory can exceed available RAM. | MEDIUM | `deep_recon.py` | UALeakAdapter, RULeakAdapter |
| RF-6 | **SQLite WAL contention** — DiscoveryEngine uses SQLite with WAL mode (good) but ThreadPoolExecutor(max_workers=10) for verification writes status updates concurrently. SQLite allows only one writer. Under contention this degrades to serial. | LOW | `discovery_engine.py` | `verify_profiles()` |
| RF-7 | **Silent failures in run_discovery.py** — `engine.run_deep_recon()` is called inside a bare `try: except Exception: print()` block. Adapter failures are logged to stdout and swallowed. No structured error tracking or failed-run flagging. | MEDIUM | `run_discovery.py` | ~180–230 |

**Recommendation:**
1. Add `RetryPolicy` (from pydantic_models.py — it already exists, just unused!) with exponential backoff + jitter to `ReconAdapter._fetch()`.
2. Implement per-adapter health tracking: after 3 consecutive failures, auto-skip for the remainder of the run.
3. Use `os.setsid` + process group kill for subprocess adapters.
4. Wrap ProcessPoolExecutor in a resilient runner that recreates the pool if `BrokenProcessPool` is raised.

---

### C.3 — Data Integrity

| # | Finding | Severity | File | Lines |
|---|---|---|---|---|
| DI-1 | **No FOREIGN KEY enforcement** — SQLite schema defines 5 tables with no FK constraints. `entity_links` references `observables` by value, not by rowid. Orphaned links can accumulate after observable deletion. | MEDIUM | `discovery_engine.py` | Schema ~100–140 |
| DI-2 | **Confidence score unbounded** — Cross-confirmation in DeepReconRunner adds +0.2 to confidence without clamping to [0, 1.0]. Edge case: confirmed hit + 3 cross-confirmations → 1.4 confidence. | MEDIUM | `deep_recon.py` | `DeepReconRunner.run()` ~3350 |
| DI-3 | **No idempotency on ingest** — `ingest_metadata()` uses INSERT OR IGNORE keyed on (obs_type, value). If the same observable arrives with a higher confidence tier from a new source, the old tier is retained. No UPSERT to keep best-tier. | MEDIUM | `discovery_engine.py` | `_classify_and_register()` |
| DI-4 | **SHA-256 chain of custody incomplete** — `intake_drop_folder.py` computes file hashes, but `deep_recon.py` does not hash adapter outputs. A compromised adapter can inject fabricated ReconHits with no integrity check. | LOW | `deep_recon.py` | All adapters |
| DI-5 | **Tier assignment is categorical, not probabilistic** — Tiers (confirmed/probable/unverified) are assigned by string matching on source_tool prefix, not by a scoring model. An adapter can self-declare `confidence=0.99` but still land in "unverified" tier. | LOW | `discovery_engine.py` | `_classify_and_register()` |

**Recommendation:**
1. Add `min(1.0, ...)` clamp to all confidence arithmetic (trivial, high ROI).
2. Change INSERT to `INSERT … ON CONFLICT DO UPDATE SET tier = MAX(tier, excluded.tier)`.
3. Add FK constraints or at minimum cascade-aware cleanup.

---

### C.4 — Module Boundaries & Coupling

| # | Finding | Severity | File | Lines |
|---|---|---|---|---|
| MB-1 | **Tight coupling: DiscoveryEngine ↔ deep_recon** — `run_deep_recon()` lazily imports `DeepReconRunner`, constructs it with hardcoded `runs_root`, reads `MODULE_PRESETS` by name, and manually re-imports hits as raw dicts. No interface contract. | HIGH | `discovery_engine.py` | `run_deep_recon()` ~1100–1200 |
| MB-2 | **Adapter classification duplicated** — `discovery_engine.py` has its own `_lane_from_source_tool()` + `_get_lane_registry()`, while `deep_recon.py` has `MODULE_LANE` dict. Two sources of truth for which adapter is fast/slow. | MEDIUM | `discovery_engine.py` ~1405–1430, `deep_recon.py` ~3100 |
| MB-3 | **No adapter interface beyond `search()` signature** — `ReconAdapter` defines `search(target_name, known_phones, known_usernames) → list[ReconHit]` but has no `health_check()`, `estimate_runtime()`, or `capabilities()` method. The engine can't adapt its behavior to adapter state. | MEDIUM | `deep_recon.py` | `ReconAdapter` base class |
| MB-4 | **bridge_legacy_phone_dossier.py talks to a non-existent API** — Makes HTTP calls to `base_url + /api/v1/graphs`, `/api/v1/runs`, `/api/v1/evidence/intake` etc. This API is defined in `api_main.py` which is never deployed. The bridge is dead code unless the FastAPI server is manually started. | HIGH | `bridge_legacy_phone_dossier.py` | All |

**Recommendation:**
1. Define a `ReconResult` protocol (or TypedDict) at the boundary. DiscoveryEngine should never import `deep_recon` directly — inject via factory.
2. Consolidate lane/priority metadata into ONE source: `deep_recon.MODULE_LANE`. DiscoveryEngine reads it.
3. Mark `bridge_legacy_phone_dossier.py` as `DEPRECATED` or wire it to the actual runtime.

---

### C.5 — Hotspots (Complexity / Change Frequency)

| Rank | File | Lines | Cyclomatic Complexity (est.) | Change Risk |
|---|---|---|---|---|
| 1 | `deep_recon.py` | 3,585 | EXTREME — 14 classes, ~60 methods, 6 subprocess dispatch paths, 2 HTTP layers (fetch + post), Playwright lifecycle, EXIF binary parsing, CSV parsing, transliteration, ProcessPoolExecutor orchestration | Any change to shared base class or worker function affects all 14 adapters |
| 2 | `discovery_engine.py` | 2,132 | VERY HIGH — God Class, Union-Find, 5-table SQLite schema, ThreadPoolExecutor, HTML rendering, deep_recon integration | Any change risks cascading through entity resolution or rendering |
| 3 | `bridge_legacy_phone_dossier.py` | 894 | MODERATE — but 100% coupled to nonexistent API | Dead on arrival |

**Recommendation:** Split by rank. Hotspot #1 (deep_recon.py) should be decomposed first — it has the highest blast radius.

---

### C.6 — Contracts & Interfaces

| # | Finding | Severity |
|---|---|---|
| CT-1 | **No schema versioning on SQLite** — Tables are created with `CREATE TABLE IF NOT EXISTS`. `_maybe_upgrade_schema()` adds columns with `ALTER TABLE ADD COLUMN` wrapped in try/except. No version counter, no migration tracking. | MEDIUM |
| CT-2 | **Adapter output is a `@dataclass` (ReconHit) but serialization to dict happens manually** in `_run_adapter_isolated()`. No `to_dict()` method, no `from_dict()` factory. Field additions are easy to drop in serialization. | MEDIUM |
| CT-3 | **Deep recon JSON report schema is implicit** — `DeepReconRunner.run()` writes a dict with keys `{target, started, finished, modules, mode, hits, errors, stats}` but there's no JSON Schema, no Pydantic model, and consumers (`_load_latest_deep_recon_report()` in DiscoveryEngine) parse it with `.get()` fallbacks. | MEDIUM |
| CT-4 | **HTML dossier is not versioned** — `render_graph_report()` generates HTML with hardcoded `v3.0.2` string but no machine-readable version field. Consumers of the HTML (analysts, downstream tools) can't detect breaking changes. | LOW |

**Recommendation:**
1. Add SQLite `PRAGMA user_version` for schema versioning — trivial change, high safety ROI.
2. Add `ReconHit.to_dict()` / `ReconHit.from_dict()` class methods.
3. Create a `deep_recon_report_schema.json` and validate on write.

---

### C.7 — Performance

| # | Finding | Severity | Impact |
|---|---|---|---|
| PF-1 | **JSONL leak scanning is O(N) per file, up to N=500,000** — Each line is JSON-parsed and string-matched. With 3 leak files, this is 1.5M JSON parses per run. | MEDIUM | ~30–90 seconds wall time per leak adapter |
| PF-2 | **Playwright cold-start in WebSearchAdapter** — `sync_playwright().start()` + `chromium.launch()` inside each search call. No browser reuse across queries. | MEDIUM | ~5 second penalty per query batch |
| PF-3 | **ThreadPoolExecutor(max_workers=10) hardcoded** for profile verification. On a 2-core CI runner, 10 threads cause context-switch overhead. On a 16-core workstation, it underutilizes. | LOW | Suboptimal but not blocking |
| PF-4 | **Entity resolution Union-Find is O(N²) on merge** — `_build_clusters()` iterates all observables × all links. For dossiers with <1000 observables this is fine. For large-scale runs it won't scale. | LOW | Not a problem at current scale |

**Recommendation:**
1. Pre-index leak JSONL files by phone prefix and name trigram for O(1) lookup.
2. Lift Playwright browser lifecycle to `DeepReconRunner` and pass to adapters.
3. Make thread pool size configurable via env var (`HANNA_VERIFY_WORKERS`).

---

### C.8 — OPSEC & Security

| # | Finding | Severity | File |
|---|---|---|---|
| OP-1 | **Proxy support is opt-in, not enforced** — `ReconAdapter.__init__()` accepts `proxy` param and builds an opener, but if `proxy` is None, all requests go direct. No kill-switch to prevent clearnet leakage. Several adapters make direct requests to target infrastructure (Ashok CMS detection, VK graph walks, OpenDataBot scraping). | CRITICAL | `deep_recon.py` |
| OP-2 | **API keys in environment variables only** — No key rotation tracking, no usage metering. `SEARCH4FACES_API_KEY`, `OPENDATABOT_API_KEY`, `FIRMS_MAP_KEY`, `TELEGRAM_BOT_TOKEN`, `GETCONTACT_TOKEN`. If any key leaks via process dump or debug log, no revocation path. | MEDIUM | Multiple adapters |
| OP-3 | **Adapter log files written in plaintext** — `_run_adapter_isolated()` writes hit details (values, confidences, source details) to plaintext `.log` files in runs directory. No encryption at rest. | MEDIUM | `deep_recon.py:_run_adapter_isolated()` |
| OP-4 | **User-Agent rotation is cosmetic** — `_USER_AGENTS` list has 5 static strings. No TLS fingerprint randomization, no header order randomization. Modern anti-bot systems fingerprint at TLS layer. | LOW | `deep_recon.py` |
| OP-5 | **SatIntelAdapter scans default directories** — When `SATINTEL_IMAGE_DIR` is unset, it scans `~/Desktop/ОСІНТ_ВИВІД/profiles` and `~/Desktop/MEDIA/2025-03-14 Фото`. This exposes the analyst's file layout to any adapter crash dump or log. | MEDIUM | `deep_recon.py:SatIntelAdapter` |

**Recommendation:**
1. **Add a `HANNA_REQUIRE_PROXY=1` env var** — when set, `ReconAdapter.__init__()` raises if `proxy` is None. This is the single highest-ROI OPSEC fix.
2. Move API keys to an encrypted keyring or at minimum a `.env` file excluded from source control with `chmod 600`.
3. Encrypt or at minimum restrict log file permissions to `0600`.

---

### C.9 — Testability

| # | Finding | Severity |
|---|---|---|
| TS-1 | **Zero tests for the Python backend** — No `tests/` directory, no `pytest.ini`, no test files anywhere in `HANNA_v3_2_clean_repo/`. | CRITICAL |
| TS-2 | **God Class is untestable in isolation** — `DiscoveryEngine` creates SQLite on init, spawns threads/processes, makes HTTP calls, writes HTML to disk. No dependency injection. Testing any method requires a real database and network. | HIGH |
| TS-3 | **Adapters are untestable without network** — `ReconAdapter._fetch()` calls `urllib.request.urlopen` directly. No request abstraction, no mock interface. Integration tests require live APIs. | HIGH |
| TS-4 | **Node.js pipeline has tests** — `tests/pipeline.test.js` exists and passes. This is the baseline to extend. | OK |

**Recommendation:**
1. This is the #1 blocker for any refactoring. Before touching a single line of production code, write:
   - Unit tests for entity resolution (pure function, no IO needed)
   - Unit tests for observable extraction (`_extract_observables`)
   - Mock-based tests for `ReconAdapter._fetch()` → inject a stub opener
   - Snapshot tests for `render_graph_report()` output structure
2. Target: 70% line coverage on `discovery_engine.py` before any refactor begins.

---

### C.10 — Code Smells

| # | Smell | Location | Severity |
|---|---|---|---|
| CS-1 | **Magic numbers everywhere** — `500000` (max JSONL lines), `512000` (max body bytes), `0.2` (cross-confirm boost), `0.65`/`0.35`/`0.55` (confidence values), `50` (max profile URLs), `10` (thread workers), `15` (adapter request cap), `120`/`300` (timeouts) | Scattered across both files | MEDIUM |
| CS-2 | **String-typed enums** — Tiers are `"confirmed"/"probable"/"unverified"`, states are `"pending"/"done"`, statuses are `"verified"/"dead"/"soft_match"/"unchecked"` — all plain strings, no Enum class | `discovery_engine.py` | LOW |
| CS-3 | **Duplicated HTML rendering** — Two complete HTML renderers with independent CSS, both doing f-string template generation. ~1100 lines of inline HTML total. | `discovery_engine.py`, `bridge_legacy_phone_dossier.py` | MEDIUM |
| CS-4 | **Unused imports in production path** — `pydantic_models.py` imports are dead. `requirements.txt` declares `fastapi`, `uvicorn`, `asyncpg` — none used. | Top-level | LOW |
| CS-5 | **Log vs print inconsistency** — `deep_recon.py` uses `logging.getLogger()`, while `discovery_engine.py` and `run_discovery.py` use `print()` for all output | All files | LOW |
| CS-6 | **Confidence is a float but tier is determined by source prefix, not by the float value** — A hit with `confidence=0.99` from deep_recon still enters as "unverified" tier if the source_tool doesn't match the confirmed-evidence path | `discovery_engine.py:_classify_and_register()` | MEDIUM |

**Recommendation:**
1. Extract magic numbers to named constants at module level.
2. Create `class Tier(str, Enum)` and `class VerificationStatus(str, Enum)`.
3. Unify rendering with a shared template engine (Jinja2 or the existing Handlebars in Node.js).

---

## D. Machine-to-Human Code Refactor Doctrine

### Principles

1. **Tests before refactors.** No structural change without ≥70% coverage on the affected module.
2. **One God, one sprint.** Decompose one God Object per sprint. Never two simultaneously.
3. **Spec must follow runtime.** Delete any spec artifact (Pydantic model, FastAPI route, SQL schema) that is not consumed by production code. Resurrect it only when you're ready to wire it.
4. **Boundary contracts are explicit.** Every module boundary gets a TypedDict or Protocol. Raw dicts at boundaries are bugs.
5. **OPSEC is a first-class constraint.** Proxy enforcement before feature work. Always.
6. **Minimize token debt.** Every function over 50 lines gets a docstring. Every module gets a 3-line header explaining what it owns.

---

## E. Canonical Execution Plan

### Phase 1: Test Foundation (Sprint 1)

| Task | Acceptance Criteria |
|---|---|
| Create `tests/` directory with pytest config | `pytest` runs and discovers tests |
| Write unit tests for `_extract_observables()` | 10+ test cases covering phone, email, username, domain, URL extraction |
| Write unit tests for Union-Find entity resolution | Test merge, cluster formation, confidence propagation |
| Write mock-based tests for `ReconAdapter._fetch()` | Mock urllib.request, verify retry behavior (once retry is added) |
| Write snapshot test for `render_graph_report()` | Assert HTML contains required sections given known SQLite state |
| **Coverage gate:** ≥60% on `discovery_engine.py` | CI blocks merge below threshold |

### Phase 2: Critical Fixes (Sprint 1, parallel)

| Task | Acceptance Criteria |
|---|---|
| Clamp confidence to `[0.0, 1.0]` everywhere | `min(1.0, ...)` on all arithmetic |
| Add `HANNA_REQUIRE_PROXY=1` enforcement | `ReconAdapter.__init__` raises `RuntimeError` when proxy is mandatory but missing |
| Replace hardcoded `~/Desktop/ОСІНТ_ВИВІД/` with `HANNA_RUNS_ROOT` env var | Single definition in new `config.py`, all files import from it |
| Add SQLite `PRAGMA user_version` migration tracking | Version incremented on schema changes, checked on startup |

### Phase 3: Decompose deep_recon.py (Sprint 2)

| Task | Acceptance Criteria |
|---|---|
| Create `adapters/` package | One file per adapter: `adapters/ua_leak.py`, `adapters/vk_graph.py`, etc. |
| Extract `ReconAdapter` base class to `adapters/base.py` | All adapters import from `adapters.base` |
| Add `RetryPolicy` to `ReconAdapter._fetch()` | 3 retries with exponential backoff (1s, 2s, 4s) + jitter. Configurable via `RetryPolicy` from pydantic_models (now wired). |
| Add per-adapter health tracking | After 3 consecutive failures, adapter is auto-skipped for remainder of run |
| Move `DeepReconRunner` to `runner.py` | Imports from `adapters/` package |
| Move `MODULES`, `MODULE_PRESETS`, `MODULE_PRIORITY`, `MODULE_LANE` to `adapters/__init__.py` | Single source of truth |
| **Coverage gate:** ≥70% on `adapters/` | Tests use mock HTTP |

### Phase 4: Decompose DiscoveryEngine (Sprint 3)

| Task | Acceptance Criteria |
|---|---|
| Extract `ingestion.py` | `ingest_metadata()`, `ingest_confirmed_evidence()` |
| Extract `entity_resolution.py` | Union-Find, `_build_clusters()`, `resolve_entities()` |
| Extract `verification.py` | `verify_profiles()`, `verify_content()`, `reverify_expired()` |
| Extract `reporting.py` | `render_graph_report()`, `get_stats()`, `get_pivot_queue()` |
| `DiscoveryEngine` becomes a thin orchestrator | <200 lines, delegates to extracted modules |
| Upgrade INSERT to UPSERT for tier escalation | `ON CONFLICT DO UPDATE SET tier = MAX(...)` |

### Phase 5: Spec Reconciliation (Sprint 4)

| Task | Acceptance Criteria |
|---|---|
| Wire Pydantic `Observable` model into `entity_resolution.py` | Replace ad-hoc `@dataclass Observable` |
| Wire Pydantic `AdapterCapability` into adapter registration | Each adapter declares capabilities, retry policy, quota windows |
| Delete or quarantine `audit_pack/specs/` | Move to `docs/aspirational/` with README explaining status |
| Clean `requirements.txt` | Only list actually-imported packages |
| Decide on `bridge_legacy_phone_dossier.py` | Either wire to running system or archive as `legacy/` |

### Phase 6: Rendering Unification (Sprint 5)

| Task | Acceptance Criteria |
|---|---|
| Extract shared CSS to standalone file | Both Python and Node.js renderers reference same CSS |
| Migrate Python HTML rendering to Jinja2 templates | Replace 1100 lines of f-string HTML |
| OR: consolidate all rendering into Node.js pipeline | Python exports JSON, Node.js renders HTML |
| Add dossier schema version field to HTML output | Machine-readable `<meta name="dossier-version" content="4.0.0">` |

---

## F. Task Graph for Cheaper LLM Execution

Each task is atomic, scoped to specific files, and has explicit stop criteria. A GPT-4o-mini / Claude Haiku class model can execute these sequentially.

```
TASK-001 | Create pytest scaffold
  FILES: HANNA_v3_2_clean_repo/tests/__init__.py, pytest.ini, conftest.py
  DO: Create empty test package, configure pytest with --strict-markers
  STOP: `pytest --collect-only` runs with 0 errors

TASK-002 | Unit tests for _extract_observables
  FILES: discovery_engine.py (read-only), tests/test_extract_observables.py (create)
  DO: Copy _extract_observables logic, write 10 parametrized test cases
  STOP: All 10 tests pass, covers phone/email/username/domain/url types

TASK-003 | Unit tests for Union-Find entity resolution
  FILES: discovery_engine.py (read-only), tests/test_entity_resolution.py (create)
  DO: Test _link_observables and _build_clusters with mock observables
  STOP: Tests cover: single cluster, multi-cluster, transitive merge, confidence propagation

TASK-004 | Add confidence clamp
  FILES: deep_recon.py (edit DeepReconRunner.run cross-confirm block)
  DO: Wrap confidence += 0.2 in min(1.0, ...)
  STOP: No confidence value in output exceeds 1.0

TASK-005 | Add HANNA_REQUIRE_PROXY enforcement
  FILES: deep_recon.py (edit ReconAdapter.__init__)
  DO: If os.environ.get("HANNA_REQUIRE_PROXY") == "1" and proxy is None: raise RuntimeError
  STOP: Test with env var set and no proxy → exception raised

TASK-006 | Create config.py for paths
  FILES: HANNA_v3_2_clean_repo/src/config.py (create)
  DO: Define RUNS_ROOT = os.environ.get("HANNA_RUNS_ROOT", str(Path.home() / "Desktop" / "ОСІНТ_ВИВІД" / "runs"))
  STOP: Single import point, grep shows no remaining hardcoded ~/Desktop paths in *.py

TASK-007 | Replace hardcoded paths
  FILES: discovery_engine.py, deep_recon.py, intake_drop_folder.py, run_discovery.py (edit)
  DO: Import RUNS_ROOT from config.py, replace all hardcoded paths
  STOP: grep -r "ОСІНТ_ВИВІД" src/ returns only config.py

TASK-008 | Add SQLite schema versioning
  FILES: discovery_engine.py (edit __init__ and schema creation)
  DO: Add PRAGMA user_version check, increment on schema changes
  STOP: Fresh DB gets version=1, old DB triggers migration path

TASK-009 | Add RetryPolicy to ReconAdapter._fetch
  FILES: deep_recon.py (edit _fetch method)
  DO: 3 retries with exponential backoff (1, 2, 4 sec) + random jitter 0-0.5s
  STOP: Unit test simulates 2 failures then success → hit returned

TASK-010 | Add adapter health tracking
  FILES: deep_recon.py (edit ReconAdapter base, DeepReconRunner)
  DO: Track consecutive failures per adapter. After 3, skip remaining calls.
  STOP: Test with always-failing mock adapter → skipped after 3rd call

TASK-011 | Extract adapters to package
  FILES: Create adapters/ directory, move each class to own file
  DO: One file per adapter, shared base.py, __init__.py with MODULES dict
  STOP: `from adapters import MODULES` works, all existing entry points function

TASK-012 | Extract DeepReconRunner to runner.py
  FILES: deep_recon.py → runner.py (new), adapters/ (import)
  DO: Move DeepReconRunner class, _run_adapter_isolated function
  STOP: `python3 runner.py --list-modules` works

TASK-013 | Zombie process prevention
  FILES: adapters/maryam.py, adapters/ashok.py, adapters/ghunt.py
  DO: Add preexec_fn=os.setsid to subprocess.run, add os.killpg in except
  STOP: Killed subprocess children don't survive parent timeout

TASK-014 | Extract ingestion module
  FILES: discovery_engine.py → ingestion.py (new)
  DO: Move ingest_metadata, ingest_confirmed_evidence, _extract_observables
  STOP: discovery_engine.py imports from ingestion.py, all tests pass

TASK-015 | Extract entity_resolution module
  FILES: discovery_engine.py → entity_resolution.py (new)
  DO: Move Union-Find, _link_observables, _build_clusters, resolve_entities
  STOP: discovery_engine.py imports from entity_resolution.py, all tests pass

TASK-016 | Extract verification module
  FILES: discovery_engine.py → verification.py (new)
  DO: Move verify_profiles, verify_content, reverify_expired
  STOP: discovery_engine.py imports from verification.py, all tests pass

TASK-017 | Extract reporting module
  FILES: discovery_engine.py → reporting.py (new)
  DO: Move render_graph_report, get_stats, get_pivot_queue, _build_lane_summary
  STOP: discovery_engine.py imports from reporting.py, all tests pass

TASK-018 | Wire Pydantic Observable model
  FILES: entity_resolution.py (edit), pydantic_models.py (read)
  DO: Replace @dataclass Observable with pydantic Observable import
  STOP: All existing tests pass, type checking clean

TASK-019 | Clean requirements.txt
  FILES: requirements.txt (edit)
  DO: Remove fastapi, uvicorn, asyncpg. Add: pytest, pydantic (keep)
  STOP: pip install -r requirements.txt succeeds, pytest runs

TASK-020 | Quarantine dead spec layer
  FILES: Move audit_pack/specs/ → docs/aspirational/
  DO: Add README.md explaining these are design documents, not production code
  STOP: No import path references audit_pack/specs/
```

---

## G. Definition of Done & Control Checklist

### Per-Task DoD

- [ ] Code change is limited to the files listed in the task scope
- [ ] All pre-existing tests continue to pass
- [ ] New tests (if any) pass and cover the stated stop criteria
- [ ] No new hardcoded paths introduced
- [ ] No confidence value can exceed 1.0
- [ ] `grep -r "FIXME\|TODO\|HACK" src/` count does not increase
- [ ] Change is committed with a conventional commit message (`fix:`, `feat:`, `refactor:`, `test:`)

### Per-Phase DoD

- [ ] Coverage gate met (stated per phase)
- [ ] No regression in existing dossier output (snapshot test)
- [ ] `python3 run_discovery.py --help` still works
- [ ] `python3 -m deep_recon --list-modules` still works (or replacement CLI)
- [ ] Node.js pipeline tests still pass (`npm test` in dossiers/)
- [ ] Docker build succeeds (both Python and Node.js containers)

### Release Gate (v4.0.0)

- [ ] DiscoveryEngine is <200 lines
- [ ] deep_recon.py no longer exists (replaced by `adapters/` + `runner.py`)
- [ ] All Pydantic models are consumed by at least one runtime import path
- [ ] `requirements.txt` lists only actually-imported packages
- [ ] SQLite schema has PRAGMA user_version ≥ 2
- [ ] Test coverage ≥70% across all Python source
- [ ] `HANNA_REQUIRE_PROXY=1` is documented and enforced in prod deployment
- [ ] All inline HTML replaced by templates or Node.js rendering
- [ ] CHANGELOG.md updated with all breaking changes
- [ ] `bridge_legacy_phone_dossier.py` is either wired or archived

---

## Appendix: Unknowns

| Item | Status | Impact |
|---|---|---|
| Contents of `audit_pack/specs/api_main.py` (1,964 lines) | NOT READ — spec-only, aspirational FastAPI control plane | May contain routing logic needed for bridge_legacy_phone_dossier.py to function |
| Contents of `audit_pack/specs/schema.sql` (1,281 lines) | NOT READ — PostgreSQL schema with RLS | Design-time only; no runtime consumer |
| Playwright version / compatibility | UNKNOWN — no pinned version in requirements | WebSearchAdapter and OpenDataBotAdapter depend on it |
| GetContact API stability | UNKNOWN — undocumented API used by UAPhoneAdapter | May break without notice |
| Leak file sizes in production | UNKNOWN — caps at 500K lines but actual sizes not measured | Memory risk depends on real data |
| Actual test coverage of Node.js pipeline | Measured at deploy but not re-measured after audit | Baseline exists |

---

*End of audit. No filler. No praise. Execute Phase 1 first.*
