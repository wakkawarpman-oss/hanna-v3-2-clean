'use strict'

async function metricsRoutes (fastify, _opts) {
  fastify.get('/metrics', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 60, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const tenantId = request.user.tenantId
    const requiredPerm = `metrics:read:${tenantId}`
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

    return reply.code(200).send({
      tenantId,
      rps_history: [5, 7, 6, 8, 9, 10, 8, 7, 9, 11],
      queue_depth: 3,
      active_sessions: 2
    })
  })
}

module.exports = metricsRoutes
