'use strict'

const USERS = [
  { id: 'user-admin-001', email: 'admin@example.com', tenantId: 'tenant1', role: 'admin' },
  { id: 'user-analyst-002', email: 'analyst@example.com', tenantId: 'tenant1', role: 'analyst' },
  { id: 'user-guest-003', email: 'guest@tenant2.com', tenantId: 'tenant2', role: 'viewer' }
]

async function userRoutes (fastify, _opts) {
  fastify.get('/users', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 30, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const tenantId = request.user.tenantId
    const requiredPerm = `user:list:${tenantId}`
    const { allowed, reason } = fastify.checkPermission(request.user, requiredPerm, tenantId)

    if (!allowed) {
      return reply.code(403).send({
        statusCode: 403,
        error: 'Forbidden',
        code: reason === 'tenant_mismatch'
          ? 'FORBIDDEN_TENANT_MISMATCH'
          : 'FORBIDDEN_PERMISSION_DENIED',
        message: reason === 'tenant_mismatch'
          ? 'Tenant boundary violation'
          : 'Insufficient permission'
      })
    }

    const tenantUsers = USERS.filter((u) => u.tenantId === tenantId)
    return reply.code(200).send({ users: tenantUsers })
  })

  fastify.post('/users', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 10, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const body = request.body || {}
    const targetTenant = String(body.tenantId || request.user.tenantId)
    const requiredPerm = `user:create:${targetTenant}`

    const { allowed, reason } = fastify.checkPermission(request.user, requiredPerm, targetTenant)
    if (!allowed) {
      return reply.code(403).send({
        statusCode: 403,
        error: 'Forbidden',
        code: reason === 'tenant_mismatch'
          ? 'FORBIDDEN_TENANT_MISMATCH'
          : 'FORBIDDEN_PERMISSION_DENIED',
        message: reason === 'tenant_mismatch'
          ? 'Tenant boundary violation'
          : 'Insufficient permission'
      })
    }

    if (!body.email || !body.role) {
      return reply.code(400).send({
        statusCode: 400,
        error: 'Bad Request',
        code: 'USER_PAYLOAD_INVALID',
        message: 'email and role are required'
      })
    }

    const user = {
      id: `user-${Date.now()}`,
      email: body.email,
      role: body.role,
      tenantId: targetTenant
    }
    USERS.push(user)

    return reply.code(201).send({ user })
  })
}

module.exports = userRoutes
