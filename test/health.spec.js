'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { randomBytes } = require('node:crypto')
const { buildApp } = require('../app')

const TEST_SECRET = 'TEST_ONLY_' + randomBytes(32).toString('hex')

test('GET /healthz mirrors health status surface', async (t) => {
  const app = await buildApp({ logger: false, jwtSecret: TEST_SECRET })
  t.after(() => app.close())

  const health = await app.inject({ method: 'GET', url: '/health' })
  const healthz = await app.inject({ method: 'GET', url: '/healthz' })

  assert.equal(health.statusCode, 200)
  assert.equal(healthz.statusCode, 200)
  assert.equal(health.json().status, healthz.json().status)
  assert.equal(health.json().version, healthz.json().version)
})