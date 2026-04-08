'use strict'

/**
 * Auth routes – login endpoint that issues a canonical JWT.
 *
 * The user store is intentionally stubbed so it can be swapped for a real
 * database or identity provider without touching the JWT contract.
 *
 * ⚠️  STUB ONLY – NOT FOR PRODUCTION USE.
 * Replace USERS with real DB lookups and use bcrypt/argon2 for password
 * hashing with constant-time comparison before any deployment.
 */

// ---------------------------------------------------------------------------
// Stub user store – replace with a real lookup in production.
// ---------------------------------------------------------------------------
const USERS = {
  'admin@example.com': {
    password: 'admin-secret',
    sub: 'user-admin-001',
    roles: ['admin'],
    permissions: ['*:*:*'],
    tenantId: 'tenant1'
  },
  'analyst@example.com': {
    password: 'analyst-secret',
    sub: 'user-analyst-002',
    roles: ['analyst'],
    permissions: [
      'evidence:read:tenant1',
      'adapter:run:shodan',
      'user:list:tenant1',
      'reports:read:tenant1',
      'reports:export:pdf',
      'metrics:read:tenant1'
    ],
    tenantId: 'tenant1'
  },
  'guest@tenant2.com': {
    password: 'guest-secret',
    sub: 'user-guest-003',
    roles: ['viewer'],
    permissions: ['evidence:read:tenant2', 'metrics:read:tenant2'],
    tenantId: 'tenant2'
  }
}

// ---------------------------------------------------------------------------
// Route schema
// ---------------------------------------------------------------------------
const loginSchema = {
  body: {
    type: 'object',
    required: ['email', 'password'],
    properties: {
      email: { type: 'string', format: 'email' },
      password: { type: 'string', minLength: 1 }
    }
  }
}

// ---------------------------------------------------------------------------
// Route plugin
// ---------------------------------------------------------------------------
async function authRoutes (fastify, _opts) {
  fastify.post('/auth/login', {
    schema: loginSchema,
    config: { rateLimit: { max: 10, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const { email, password } = request.body

    const user = USERS[email]
    // NOTE: Plain equality is acceptable here because USERS is a stub.
    // A real implementation must use bcrypt/argon2 with constant-time comparison.
    if (!user || user.password !== password) {
      return reply.code(401).send({
        statusCode: 401,
        error: 'Unauthorized',
        code: 'AUTH_INVALID_CREDENTIALS',
        message: 'Invalid credentials'
      })
    }

    // jti is a unique token id using cryptographically secure randomness.
    const jti = require('node:crypto').randomUUID()

    const payload = {
      sub: user.sub,
      roles: user.roles,
      permissions: user.permissions,
      tenantId: user.tenantId,
      jti
    }

    // @fastify/jwt respects expiresIn via sign options.
    const token = await reply.jwtSign(payload, { expiresIn: '1h' })

    return reply.code(200).send({ accessToken: token })
  })
}

module.exports = authRoutes
