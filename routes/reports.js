'use strict'

const REPORTS = [
  { id: 'rpt-001', tenantId: 'tenant1', title: 'Tenant 1 threat report' },
  { id: 'rpt-002', tenantId: 'tenant2', title: 'Tenant 2 risk report' }
]

async function reportRoutes (fastify, _opts) {
  fastify.get('/reports', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 30, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const tenantId = request.user.tenantId
    const requiredPerm = `reports:read:${tenantId}`
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
      reports: REPORTS.filter((r) => r.tenantId === tenantId)
    })
  })

  fastify.post('/reports/:id/export', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const tenantId = request.user.tenantId
    const format = String(request.body?.format || 'pdf')
    if (!['pdf', 'json'].includes(format)) {
      return reply.code(400).send({
        statusCode: 400,
        error: 'Bad Request',
        code: 'REPORT_EXPORT_FORMAT_INVALID',
        message: `Unsupported export format '${format}'`
      })
    }

    const requiredPerm = `reports:export:${format}`
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

    const report = REPORTS.find((r) => r.id === request.params.id && r.tenantId === tenantId)
    if (!report) {
      return reply.code(404).send({
        statusCode: 404,
        error: 'Not Found',
        code: 'REPORT_NOT_FOUND',
        message: `Report '${request.params.id}' not found`
      })
    }

    return reply.code(202).send({
      status: 'accepted',
      jobId: `job-${Date.now()}`,
      reportId: report.id,
      format,
      tenantId
    })
  })
}

module.exports = reportRoutes
