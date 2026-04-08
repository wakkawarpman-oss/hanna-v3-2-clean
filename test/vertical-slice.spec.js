'use strict'

/**
 * Vertical slice tests: Fastify JWT/RBAC auth layer.
 *
 * Run with: node --test test/vertical-slice.spec.js
 */

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { randomBytes } = require('node:crypto')
const { buildApp } = require('../app')

// Use a fresh random secret per test run to prevent accidental reuse.
const TEST_SECRET = 'TEST_ONLY_' + randomBytes(32).toString('hex')

// ---------------------------------------------------------------------------
// Helper: build app with a fixed test secret.
// ---------------------------------------------------------------------------
function buildTestApp () {
  return buildApp({ logger: false, jwtSecret: TEST_SECRET })
}

// ---------------------------------------------------------------------------
// Helper: fire an HTTP request against the Fastify test instance.
// ---------------------------------------------------------------------------
async function request (app, method, url, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (opts.body) {
    headers['content-type'] = 'application/json'
  }
  const response = await app.inject({
    method,
    url,
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined
  })
  return {
    statusCode: response.statusCode,
    body: response.json()
  }
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test('login success returns access token with canonical payload', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'POST', '/auth/login', {
    body: { email: 'analyst@example.com', password: 'analyst-secret' }
  })

  assert.equal(res.statusCode, 200, 'should return 200')
  assert.ok(res.body.accessToken, 'should include accessToken')

  // Decode and verify canonical payload fields (without verification — just decode)
  const parts = res.body.accessToken.split('.')
  assert.equal(parts.length, 3, 'should be a 3-part JWT')

  const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
  assert.ok(payload.sub, 'payload must include sub')
  assert.ok(Array.isArray(payload.roles), 'payload must include roles array')
  assert.ok(Array.isArray(payload.permissions), 'payload must include permissions array')
  assert.ok(payload.tenantId, 'payload must include tenantId')
  assert.ok(payload.jti, 'payload must include jti')
  assert.ok(payload.iat, 'payload must include iat')
  assert.ok(payload.exp, 'payload must include exp')
})

test('login with invalid credentials returns 401', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'POST', '/auth/login', {
    body: { email: 'analyst@example.com', password: 'wrong-password' }
  })

  assert.equal(res.statusCode, 401, 'should return 401')
  assert.equal(res.body.code, 'AUTH_INVALID_CREDENTIALS')
})

test('public GET /adapters returns adapter list without auth', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'GET', '/adapters')

  assert.equal(res.statusCode, 200)
  assert.ok(Array.isArray(res.body.adapters), 'should return adapters array')
  assert.ok(res.body.adapters.length > 0, 'should have at least one adapter')
})

test('protected route succeeds with valid permission (adapter:run:shodan)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  // analyst@example.com has permissions: ['evidence:read:tenant1', 'adapter:run:shodan']
  const loginRes = await request(app, 'POST', '/auth/login', {
    body: { email: 'analyst@example.com', password: 'analyst-secret' }
  })
  assert.equal(loginRes.statusCode, 200)
  const token = loginRes.body.accessToken

  const res = await request(app, 'POST', '/adapters/shodan/run', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 202, `expected 202, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.adapterId, 'shodan')
  assert.equal(res.body.status, 'accepted')
})

test('protected route succeeds with wildcard permission (adapter:run:*)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  // admin@example.com has permissions: ['*:*:*']
  const loginRes = await request(app, 'POST', '/auth/login', {
    body: { email: 'admin@example.com', password: 'admin-secret' }
  })
  assert.equal(loginRes.statusCode, 200)
  const token = loginRes.body.accessToken

  const res = await request(app, 'POST', '/adapters/ghunt/run', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 202, `expected 202, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
})

test('403 returned for insufficient permission (viewer tries to run adapter)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  // guest@tenant2.com only has 'evidence:read:tenant2' — no adapter:run permissions
  const loginRes = await request(app, 'POST', '/auth/login', {
    body: { email: 'guest@tenant2.com', password: 'guest-secret' }
  })
  assert.equal(loginRes.statusCode, 200)
  const token = loginRes.body.accessToken

  const res = await request(app, 'POST', '/adapters/shodan/run', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 403, `expected 403, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.error, 'Forbidden')
  assert.equal(res.body.code, 'FORBIDDEN_PERMISSION_DENIED')
})

test('tenant mismatch is denied – unit test of checkPermission utility', async (_t) => {
  // The HTTP route enforces tenant boundary by deriving requiredTenantId from
  // the JWT payload itself (request.user.tenantId), so a tampered token would
  // fail JWT signature verification before reaching the permission check.
  // This unit test exercises the underlying enforcement logic directly.
  const { checkPermission } = require('../plugins/jwt-rbac')

  const fakePayload = {
    sub: 'user-x',
    roles: ['analyst'],
    permissions: ['adapter:run:shodan'],
    tenantId: 'tenant1', // user's tenant
    jti: 'test-jti'
  }

  // Required tenant is 'tenant2' — this is a cross-tenant mismatch
  const result = checkPermission(fakePayload, 'adapter:run:shodan', 'tenant2')
  assert.equal(result.allowed, false, 'should deny when tenants differ')
  assert.equal(result.reason, 'tenant_mismatch')
})

test('401 returned when no token is provided to protected route', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'POST', '/adapters/shodan/run')

  assert.equal(res.statusCode, 401, `expected 401, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.code, 'AUTH_INVALID_OR_EXPIRED_TOKEN')
})

test('401 returned when malformed bearer token is provided', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'POST', '/adapters/shodan/run', {
    headers: { Authorization: 'Bearer definitely-not-a-jwt' }
  })

  assert.equal(res.statusCode, 401, `expected 401, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.code, 'AUTH_INVALID_OR_EXPIRED_TOKEN')
})

test('401 returned when expired token is provided', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const expiredPayload = {
    sub: 'user-expired-001',
    roles: ['analyst'],
    permissions: ['adapter:run:shodan'],
    tenantId: 'tenant1',
    jti: 'expired-token-jti'
  }

  const expiredToken = app.jwt.sign(expiredPayload, { expiresIn: '-1s' })

  const res = await request(app, 'POST', '/adapters/shodan/run', {
    headers: { Authorization: `Bearer ${expiredToken}` }
  })

  assert.equal(res.statusCode, 401, `expected 401, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.code, 'AUTH_INVALID_OR_EXPIRED_TOKEN')
})

test('404 returned when adapter id is unknown', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const loginRes = await request(app, 'POST', '/auth/login', {
    body: { email: 'admin@example.com', password: 'admin-secret' }
  })
  assert.equal(loginRes.statusCode, 200)

  const res = await request(app, 'POST', '/adapters/unknown_adapter/run', {
    headers: { Authorization: `Bearer ${loginRes.body.accessToken}` }
  })

  assert.equal(res.statusCode, 404, `expected 404, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.code, 'ADAPTER_NOT_FOUND')
})

test('superadmin *:*:* bypasses all permission checks', async (t) => {
  const { checkPermission } = require('../plugins/jwt-rbac')

  const adminPayload = {
    sub: 'user-admin',
    roles: ['admin'],
    permissions: ['*:*:*'],
    tenantId: 'tenant1',
    jti: 'test-jti'
  }

  const result = checkPermission(adminPayload, 'adapter:run:anything', 'tenant1')
  assert.equal(result.allowed, true)
  assert.equal(result.reason, 'superadmin')
})
