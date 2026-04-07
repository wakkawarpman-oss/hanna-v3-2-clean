# HANNA v3.2 Clean — Implementation Status and Next-Stage Plan (2026-04-08)

## Executive Status

HANNA is no longer in the prototype phase.

The clean repository now represents a working OSINT orchestration platform in late integration and release hardening. The core runtime, discovery fusion, HTML dossier rendering, machine-readable exports, and operator cleanup flows are already implemented.

This document reflects the current shipped system and the next implementation wave, rather than an earlier adapter-expansion-only plan.

## What Is Already Shipped

### Core Runtime

- Unified CLI in `src/cli.py`
- Three execution modes: `manual`, `aggregate`, `chain`
- Preflight checks for tool binaries, env vars, and runtime prerequisites
- Reset / cleanup command for generated state

### Discovery and Fusion Layer

- Metadata ingestion into the discovery database
- Observable registration and deduplication
- Entity resolution and corroboration tracking
- Rejected-target handling and verification passes
- HTML dossier rendering from the resolved graph

### Operator Safety and Reporting

- Safe-by-default dossier redaction
- Supported redaction modes: `internal`, `shareable`, `strict`
- Report-mode propagation through canonical and legacy entrypoints
- Sanitized chain dossier inclusion in ZIP evidence packs

### Export Surface

- JSON export for serialized `RunResult`
- STIX-like bundle export for downstream systems
- ZIP export containing machine-readable artifacts and rendered dossier
- ZIP manifest now records the selected dossier `report_mode`

### Regression Coverage

- Exporter contract tests
- CLI contract tests
- Chain runner report-mode tests
- Discovery redaction tests
- Runtime reset tests

## Current Integrated Adapter Base

These adapters are already integrated into HANNA and produce structured results through the shared orchestration layer.

| Adapter | Category | Current Role |
|---------|----------|--------------|
| ua_leak | Person / leaks | Corroboration and leak enrichment |
| ru_leak | Person / leaks | Additional leak-side corroboration |
| vk_graph | Social | Social graph and platform traces |
| avito | Marketplace | Marketplace footprint and seller traces |
| ua_phone | Phone | Phone enrichment and caller identity signals |
| maryam | Framework wrapper | External framework bridge |
| ashok | Infrastructure | Infrastructure and public-host enrichment |
| ghunt | Google OSINT | Google-account enrichment |
| social_analyzer | Username OSINT | Cross-platform username footprint |
| satintel | GEOINT / EXIF | Spatial and media-side enrichment |
| search4faces | Face search | Face-recognition enrichment |
| web_search | Web discovery | Search-engine and browser-assisted discovery |
| opendatabot | UA registry | Business and registry linkage |
| firms | Satellite / specialized | Specialized geospatial enrichment |

## System Layers

### 1. Adapter Layer

Adapters wrap external tools and APIs and emit normalized hits instead of tool-specific raw output.

Responsibilities:

- validate target compatibility,
- call CLI or API sources,
- parse external output,
- return normalized observables with confidence and provenance.

### 2. Runner Layer

The runner layer exposes three execution modes:

- `manual` for single-adapter direct execution,
- `aggregate` for parallel batches across selected modules,
- `chain` for ingest → resolve → recon → verify → render.

### 3. Discovery Engine

The discovery engine turns raw findings into a coherent operational picture:

- ingest metadata and evidence,
- register observables,
- link corroborating signals,
- resolve entities,
- verify profiles and content,
- render dossiers.

### 4. Export and Ops Layer

This layer gives the platform operational maturity:

- JSON/STIX/ZIP exports,
- runtime cleanup and reset,
- machine-readable evidence handoff,
- preflight gating before runs.

## Current Gaps

The main remaining gaps are no longer in the existence of the platform, but in expansion and operational refinement.

### Documentation and Operator Runbooks

- keep README and plan aligned with the clean repository reality,
- document recommended presets and report-mode guidance,
- document release and smoke-check procedures.

### Adapter Expansion

The platform core is ready for the next adapter wave. The highest-value missing integrations remain the infrastructure and enrichment modules identified below.

### End-to-End Acceptance Flows

- add more scenario-style tests around `chain` with exports,
- add smoke validation for ZIP plus sanitized dossier behavior,
- keep release verification fast and repeatable.

## Next Adapter Wave

The next expansion should focus on adapters that fit the existing runtime cleanly and materially improve coverage.

### Phase 1 — Infrastructure Expansion

Priority: highest ROI for infrastructure recon and downstream pivoting.

Planned adapters:

- `httpx_probe`
- `nuclei`
- `katana`
- `naabu`
- `subfinder`
- `amass`

Intended outcome:

- discover subdomains,
- resolve live HTTP surfaces,
- probe tech stack,
- enumerate ports,
- identify templated findings,
- expand reachable endpoint inventory.

### Phase 2 — Person and Account Expansion

Priority: direct payoff for person-centric investigations.

Planned adapters:

- `holehe`
- `blackbird`
- `censys`
- `metagoofil`

Intended outcome:

- widen account-footprint discovery,
- map email-to-service presence,
- add certificate and host-side enrichment,
- mine document metadata for emails and usernames.

### Phase 3 — Existing Tool Wrappers

Priority: convert already-installed tooling into first-class platform modules.

Planned adapters:

- `nmap`
- `shodan`

Optional wrappers depending on operational value:

- `sherlock`
- `maigret`
- `phoneinfoga`
- `theHarvester`

### Phase 4 — Framework Bridges

Priority: controlled integration of heavier external ecosystems.

Planned adapters:

- `reconng`
- `eyewitness`

These should only be promoted when the parsing contract is stable and operational noise is acceptable.

## Tools That Should Stay External

Some tools are still useful, but should not be promoted to first-class automated adapters by default.

| Tool | Reason |
|------|--------|
| reconFTW | External orchestrator that should call HANNA, not be modeled as a HANNA adapter |
| SpiderFoot | Parallel ecosystem better handled through export/import boundaries |
| Maltego | Visualization consumer of exports rather than a data producer |
| gobuster / feroxbuster | Useful but too noisy for default automated integration |
| OSINT Framework | Reference catalog, not a runnable adapter |
| Kagi / Perplexity | Search engines, not stable adapter targets |
| RustScan | Overlaps with `naabu` without enough advantage for the core pipeline |

## Implementation Contract for New Adapters

Every new adapter must fit the existing platform model.

```python
class XxxAdapter(ReconAdapter):
    name = "xxx"
    region = "global"

    def search(self, target_name, known_phones, known_usernames) -> list[ReconHit]:
        # 1. Validate input type
        # 2. Call CLI or API
        # 3. Parse raw output
        # 4. Return normalized hits with provenance
```

Required follow-through after implementation:

1. Register the adapter in `adapters/__init__.py` and the main registry.
2. Add priority, lane, and preset wiring.
3. Document required env vars and binary expectations.
4. Add smoke coverage and at least one parser-focused regression test.
5. Run strict preflight before operational rollout.

## Delivery Priorities From Here

### Priority A — Keep the Core Stable

- preserve clean export contracts,
- preserve redaction guarantees,
- keep chain dossier behavior deterministic,
- keep reset safe and explicit.

### Priority B — Expand With Discipline

- integrate only tools that emit useful observables,
- prefer adapters that fit the shared result model cleanly,
- avoid noisy wrappers unless there is a strong operational case.

### Priority C — Make Operations Boring

- clean docs,
- repeatable smoke checks,
- stable folder and naming conventions,
- explicit runbooks for internal vs shareable outputs.

## Bottom Line

HANNA already has the shape of a productized OSINT execution layer.

The system has moved beyond “can we make the tools run” and into “can we make the platform safe, stable, exportable, and expandable without chaos.” The next implementation wave should extend adapter coverage while preserving the clean runtime and operator surface that now exists.
