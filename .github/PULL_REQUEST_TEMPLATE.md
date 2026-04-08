## What is changing

- [ ] Introduce or update vertical-slice behavior for auth, routing, and permission flow.
- [ ] Keep changes scoped to one coherent behavior slice per PR.
- [ ] Preserve backward compatibility for unaffected routes and modules.

## Why this change

Describe the user-visible behavior and the risk reduced by this PR.

## Gate 1: JWT decode -> Contract (Acceptance Criteria)

- [ ] JWT claims contract is explicit and verified: sub, roles, permissions, tenantId, jti, iat, exp.
- [ ] Negative token suite exists and passes:
  - [ ] malformed token -> 401
  - [ ] expired token -> 401
  - [ ] missing Authorization header -> 401
  - [ ] tenant mismatch -> 403
  - [ ] insufficient permission -> 403
- [ ] Auth contract is stable and documented:
  - [ ] POST /api/auth/login request and response schema
  - [ ] canonical error payload for 401 and 403
- [ ] Protected routes validate Authorization: Bearer <token> and enforce tenant boundary.
- [ ] Permission model uses resource:action:scope with wildcard behavior covered by tests.
- [ ] Contract smoke tests are independent from coverage thresholds.

## Test strategy

- [ ] Vertical-slice contract tests added or updated.
- [ ] Existing unrelated tests remain green.
- [ ] Local command output included in PR body (or CI link if private):
  - [ ] npm test
  - [ ] any additional contract test command

## Security and reliability checks

- [ ] No fallback JWT secret in production path.
- [ ] Deny-by-default behavior preserved.
- [ ] No privilege escalation path via malformed claims.

## Follow-up work

List deferred tasks that are intentionally out of scope for this PR.

## Reviewer checklist

- [ ] Scope is minimal and behavior-focused.
- [ ] Contract changes are backward compatible or clearly versioned.
- [ ] CI job outcomes are attached and reproducible.