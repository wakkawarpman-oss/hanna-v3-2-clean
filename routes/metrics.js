'use strict'

const pkg = require('../package.json')

async function metricsRoutes (fastify, _opts) {
  fastify.get('/health', async (_request, reply) => {
    const memory = process.memoryUsage()
    const degraded = memory.heapUsed > 400 * 1024 * 1024
    const payload = {
      status: degraded ? 'degraded' : 'healthy',
      uptime: process.uptime(),
      timestamp: Date.now(),
      memory,
      parserCache: Number(process.env.PARSER_CACHE_SIZE || 0),
      version: pkg.version
    }

    return reply.code(degraded ? 503 : 200).send(payload)
  })

  fastify.get('/metrics', {
    config: { rateLimit: { max: 60, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const publicMetrics = process.env.METRICS_PUBLIC === '1'
    let tenantId = 'public'

    if (!publicMetrics) {
      await fastify.authenticate(request, reply)
      if (reply.sent) return

      tenantId = request.user.tenantId
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
