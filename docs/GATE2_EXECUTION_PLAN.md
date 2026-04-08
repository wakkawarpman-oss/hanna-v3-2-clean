# Gate 2 Execution Plan: Core Routes -> Tests -> Security

Status baseline before Gate 2:
- Node vertical slice is green (9/9)
- Python AdapterResult schema is green (26/26)

Step 1 completion snapshot:
- Added negative-path contract tests for malformed token, expired token, and unknown adapter
- Hardened deterministic error payload codes:
	- AUTH_INVALID_CREDENTIALS
	- AUTH_INVALID_OR_EXPIRED_TOKEN
	- FORBIDDEN_PERMISSION_DENIED
	- FORBIDDEN_TENANT_MISMATCH
	- ADAPTER_NOT_FOUND
- Verified baseline compatibility after Step 1:
	- Node vertical-slice tests: 12/12 green
	- Python AdapterResult schema tests: 26/26 green

Step 2 execution snapshot:
- Added core route surface:
	- GET /users
	- POST /users
	- GET /reports
	- POST /reports/:id/export
	- GET /metrics
- Added dedicated Step 2 contract tests in test/core-routes.spec.js
- Current validation on implementation branch:
	- Node route contract tests: 21/21 green
	- Python regression suite: 171/171 green

## Task 1: Freeze and extend auth contract behavior

- Endpoints in scope:
	- POST /auth/login
- Files to change:
	- app.js
	- routes/auth.js
	- plugins/jwt-rbac.js
	- test/vertical-slice.spec.js
- Tests to add or update:
	- malformed token -> 401
	- expired token -> 401
	- missing Authorization -> 401
	- insufficient permission -> 403
	- tenant mismatch -> 403
- Acceptance criteria:
	- JWT claims contract remains canonical: sub, roles, permissions, tenantId, jti, iat, exp
	- 401 and 403 error payload shapes are deterministic
	- no fallback secret in production path

## Task 2: Expand core adapter route coverage

- Endpoints in scope:
	- GET /adapters
	- POST /adapters/:id/run
- Files to change:
	- routes/adapters.js
	- test/vertical-slice.spec.js
- Tests to add or update:
	- adapter not found -> 404
	- wildcard permission allows run -> 202
	- resource-specific permission allows only that adapter
	- route-level rate limit behavior for /adapters/:id/run
- Acceptance criteria:
	- adapter existence validation is deterministic
	- permission checks enforce resource:action:scope and wildcard logic
	- success responses for run requests remain 202 accepted

## Task 3: Separate CI contract smoke from quality gates

- Pipelines in scope:
	- Node Vertical Slice workflow
	- Python test workflow (or equivalent test command in CI)
- Files to change:
	- .github/workflows/node-vertical-slice.yml
	- add or update dedicated coverage workflow file under .github/workflows/
- Tests and checks:
	- contract smoke job runs fast and fails only on behavior regression
	- coverage gate runs in separate job/workflow with explicit thresholds
- Acceptance criteria:
	- contract smoke remains green when behavior is correct
	- coverage failures do not masquerade as contract failures

## Task 4: AdapterResult contract lock for cross-language boundary

- Boundary in scope:
	- Python adapter outcomes consumed/exported by CLI layer
- Files to change:
	- src/schemas/adapter_result.py
	- src/schemas/__init__.py
	- src/cli.py
	- tests/test_adapter_result_schema.py
- Tests to add or update:
	- legacy payload normalization edge cases
	- malformed non-dict outcomes produce machine-readable error object
	- export pipeline fails fast on invalid outcomes
- Acceptance criteria:
	- schema remains backward-compatible for accepted legacy inputs
	- validation errors stay machine-readable and stable for operators

## Task 5: Gate 2 security checks (minimum viable)

- Security scope:
	- JWT handling and route authorization boundary
	- auth and adapter routes
- Files to change:
	- routes/auth.js
	- routes/adapters.js
	- plugins/jwt-rbac.js
	- CI workflow definitions for security scan execution
- Checks to enforce:
	- no hardcoded production secrets
	- deny-by-default permission behavior preserved
	- static scan and dependency audit integrated into CI
- Acceptance criteria:
	- high-severity findings: zero before merge
	- auth regressions block merge

## Exit criteria for Gate 2

- Node tests in scope: green
- Python schema tests in scope: green
- Contract smoke and coverage jobs are split and stable
- No open high-severity security findings in auth/route boundary
