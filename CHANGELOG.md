# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Production Readiness Hardening
- Added TUI validation and release scripts in `package.json`:
  - `tui:check`
  - `test:tui`
  - `security`
  - `release`
- Added CLI binary mapping for `hanna` command in Node package metadata.
- Added core runtime env keys (`JWT_SECRET`, `API_URL`, `TENANT_ID`) to `.env.example`.
- Added TUI quick start section to `README.md`.
- Added dedicated GitHub Actions workflow for TUI health checks.
- Added `Dockerfile.tui` for containerized TUI runtime.
- Added `scripts/hanna.sh` quick operations toolkit (`start`, `tui`, `test`, `contract`, `status`, `logs`, `stop`, `init`).
- Added `scripts/install.sh` to install `hanna` command under `~/.hanna` and link it into `~/.local/bin`.
- Added `docker-compose.tui.yml` helper for API + TUI local orchestration.

### Gate 2 Step 2
- Added tenant-scoped core routes:
  - GET /users
  - POST /users
  - GET /reports
  - POST /reports/:id/export
  - GET /metrics
- Added deterministic permission and tenant-boundary enforcement for new route surface.
- Added Step 2 contract tests in `test/core-routes.spec.js` covering auth, permission, 404, and success paths.
- Updated Node test command to run all route contract specs under `test/*.spec.js`.

### Gate 2 Step 1
- Hardened auth-routing and adapter authorization contract for:
  - POST /auth/login
  - GET /adapters
  - POST /adapters/:id/run
- Locked deterministic contract outcomes:
  - 401 for authentication failures (missing, malformed, invalid, expired token)
  - 403 for tenant boundary and permission violations
  - 404 for unknown adapter
- Reinforced tenant-scoped RBAC behavior, including wildcard and resource-specific permission checks.
- Expanded contract-smoke negative-path coverage for auth and adapter boundary scenarios.
- Preserved CI gate separation:
  - contract-smoke validates behavior regressions
  - coverage quality remains a separate gate
- Verified baseline compatibility:
  - Node vertical-slice remains green
  - Python AdapterResult schema remains unchanged in this step

Impact:
- Core Migration now has a stable, test-verified auth/adapter boundary for further route expansion in subsequent Gate 2 tasks.
