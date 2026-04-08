# Changelog

All notable changes to this project are documented in this file.

## Unreleased

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
