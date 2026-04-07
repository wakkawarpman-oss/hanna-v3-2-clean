# Architecture Overview

## Flow

1. Metadata ingestion (`run_discovery.py` -> `DiscoveryEngine.ingest_metadata`)
2. Entity resolution and clustering (`DiscoveryEngine.resolve_entities`)
3. Deep recon expansion (`DiscoveryEngine.run_deep_recon` -> `DeepReconRunner.run`)
4. Observable feedback loop into DB + queue
5. Verification (`--verify`, `--verify-content`)
6. HTML dossier generation (`DiscoveryEngine.render_graph_report`)

## Deep Recon Execution Model

- Priority lanes: P0..P3
- Runtime lanes: fast / slow
- Worker isolation via process pool
- Graceful degradation: per-module error capture without global stop

## Batch Support

`run_discovery.py --targets-file` executes deep recon per target and injects per-target seeds:

- `known_phones_override`
- `known_usernames_override`

Both are merged with engine-known observables and deduplicated before module execution.
