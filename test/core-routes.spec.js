'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { randomBytes } = require('node:crypto')
const { buildApp } = require('../app')

const TEST_SECRET = 'TEST_ONLY_' + randomBytes(32).toString('hex')

function buildTestApp () {
  return buildApp({ logger: false, jwtSecret: TEST_SECRET })
}

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

async function login (app, email, password) {
  const res = await request(app, 'POST', '/auth/login', {
    body: { email, password }
  })
  assert.equal(res.statusCode, 200)
  return res.body.accessToken
}

test('GET /users requires auth (401)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const res = await request(app, 'GET', '/users')
  assert.equal(res.statusCode, 401)
  assert.equal(res.body.code, 'AUTH_INVALID_OR_EXPIRED_TOKEN')
})

test('GET /users returns tenant-scoped users for analyst', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'GET', '/users', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 200)
  assert.ok(Array.isArray(res.body.users))
  assert.ok(res.body.users.every((u) => u.tenantId === 'tenant1'))
})

test('POST /users denied for analyst (403)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'POST', '/users', {
    headers: { Authorization: `Bearer ${token}` },
    body: { email: 'new-user@example.com', role: 'viewer' }
  })

  assert.equal(res.statusCode, 403)
  assert.equal(res.body.code, 'FORBIDDEN_PERMISSION_DENIED')
})

test('POST /users allowed for admin superadmin (201)', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'admin@example.com', 'admin-secret')
  const res = await request(app, 'POST', '/users', {
    headers: { Authorization: `Bearer ${token}` },
    body: { email: 'operator@tenant1.com', role: 'analyst', tenantId: 'tenant1' }
  })

  assert.equal(res.statusCode, 201)
  assert.equal(res.body.user.tenantId, 'tenant1')
})

test('GET /reports returns tenant-scoped reports', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'GET', '/reports', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 200)
  assert.ok(Array.isArray(res.body.reports))
  assert.ok(res.body.reports.every((r) => r.tenantId === 'tenant1'))
})

test('POST /reports/:id/export returns 202 for permitted user', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'POST', '/reports/rpt-001/export', {
    headers: { Authorization: `Bearer ${token}` },
    body: { format: 'pdf' }
  })

  assert.equal(res.statusCode, 202)
  assert.ok(res.body.jobId)
  assert.equal(res.body.format, 'pdf')
})

test('POST /reports/:id/export returns 403 for unsupported permission format', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'POST', '/reports/rpt-001/export', {
    headers: { Authorization: `Bearer ${token}` },
    body: { format: 'json' }
  })

  assert.equal(res.statusCode, 403)
  assert.equal(res.body.code, 'FORBIDDEN_PERMISSION_DENIED')
})

test('POST /reports/:id/export returns 404 for unknown report', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'POST', '/reports/rpt-999/export', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 404)
  assert.equal(res.body.code, 'REPORT_NOT_FOUND')
})

test('GET /metrics returns tenant-scoped metrics for permitted user', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'analyst@example.com', 'analyst-secret')
  const res = await request(app, 'GET', '/metrics', {
    headers: { Authorization: `Bearer ${token}` }
  })

  assert.equal(res.statusCode, 200)
  assert.equal(res.body.tenantId, 'tenant1')
  assert.ok(Array.isArray(res.body.rps_history))
})

test('GET /metrics denied when permission is missing', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const token = await login(app, 'guest@tenant2.com', 'guest-secret')

  // Guest can read only tenant2 metrics. Sign a token with tenant1 to simulate
  // an attempted cross-tenant metrics read and verify boundary denial.
  const crossTenantToken = app.jwt.sign({
    sub: 'user-guest-003',
    roles: ['viewer'],
    permissions: ['metrics:read:tenant2'],
    tenantId: 'tenant1',
    jti: 'guest-cross-tenant'
  }, { expiresIn: '1h' })

  void token
  const res = await request(app, 'GET', '/metrics', {
    headers: { Authorization: `Bearer ${crossTenantToken}` }
  })

  assert.equal(res.statusCode, 403)
  assert.equal(res.body.code, 'FORBIDDEN_PERMISSION_DENIED')
})

test('GET /metrics returns 401 for expired token', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const expiredToken = app.jwt.sign({
    sub: 'user-admin-001',
    roles: ['admin'],
    permissions: ['*:*:*'],
    tenantId: 'tenant1',
    jti: 'expired-admin'
  }, { expiresIn: '-1s' })

  const res = await request(app, 'GET', '/metrics', {
    headers: { Authorization: `Bearer ${expiredToken}` }
  })

  assert.equal(res.statusCode, 401)
  assert.equal(res.body.code, 'AUTH_INVALID_OR_EXPIRED_TOKEN')
})

test('wildcard permissions allow create, read-only permissions block create', async (t) => {
  const app = await buildTestApp()
  t.after(() => app.close())

  const wildcardToken = app.jwt.sign({
    sub: 'user-admin-001',
    roles: ['admin'],
    permissions: ['user:*', 'user:list:tenant1'],
    tenantId: 'tenant1',
    jti: 'wild-user'
  }, { expiresIn: '1h' })

  const readOnlyToken = app.jwt.sign({
    sub: 'user-read-001',
    roles: ['viewer'],
    permissions: ['user:list:tenant1'],
    tenantId: 'tenant1',
    jti: 'readonly-user'
  }, { expiresIn: '1h' })

  const createAllowed = await request(app, 'POST', '/users', {
    headers: { Authorization: `Bearer ${wildcardToken}` },
    body: { email: 'wildcard-user@tenant1.com', role: 'analyst', tenantId: 'tenant1' }
  })
  assert.equal(createAllowed.statusCode, 201)

  const createDenied = await request(app, 'POST', '/users', {
    headers: { Authorization: `Bearer ${readOnlyToken}` },
    body: { email: 'readonly-user@tenant1.com', role: 'viewer', tenantId: 'tenant1' }
  })
  assert.equal(createDenied.statusCode, 403)
  assert.equal(createDenied.body.code, 'FORBIDDEN_PERMISSION_DENIED')
})
