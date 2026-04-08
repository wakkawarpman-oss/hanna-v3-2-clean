# Gate 1 Checklist: JWT decode -> Contract

## Objective

Restore and lock a reliable contract baseline before Core Migration expands scope.

## Contract baseline

- JWT claims are canonical and required where applicable:
  - sub
  - roles
  - permissions
  - tenantId
  - jti
  - iat
  - exp
- Permission format is resource:action:scope with wildcard support.
- Access control is deny-by-default.

## Required API behaviors

- POST /api/auth/login returns a token with canonical claims.
- Protected routes require Authorization: Bearer <token>.
- Tenant boundary mismatch returns 403.
- Permission mismatch returns 403.
- Invalid, expired, or malformed token returns 401.

## Required test coverage for contract behavior

- Positive path:
  - login success
  - authorized route access
- Negative path:
  - missing Authorization
  - malformed token
  - expired token
  - tenant mismatch
  - insufficient permission

## CI policy for Gate 1

- Contract smoke tests must fail only on behavior regressions.
- Coverage thresholds are enforced in a dedicated quality workflow, not in contract smoke job.
- CI output must include exact command and result summary.

## Exit criteria (ready for Core Migration)

- test-vertical-slice is green in CI.
- Contract behaviors above are validated by automated tests.
- No unresolved security finding for auth and permission checks.
- Core scope can proceed without redefining auth contract.