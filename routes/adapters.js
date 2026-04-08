'use strict'

/**
 * Adapter routes.
 *
 * Public:
 *   GET /adapters – list available adapters (no auth required)
 *
 * Protected:
 *   POST /adapters/:id/run – run an adapter (requires adapter:run:* or
 *                            resource-specific adapter:run:<id> permission,
 *                            and a matching tenantId)
 */

// ---------------------------------------------------------------------------
// Stub adapter registry – in production, load from the Python adapter layer
// or a shared config store.
// ---------------------------------------------------------------------------
const ADAPTERS = [
  { id: 'shodan', name: 'Shodan', description: 'Infrastructure and host enrichment' },
  { id: 'ghunt', name: 'GHunt', description: 'Google-account enrichment' },
  { id: 'social_analyzer', name: 'Social Analyzer', description: 'Cross-platform username footprint' }
]

// ---------------------------------------------------------------------------
// Route plugin
// ---------------------------------------------------------------------------
async function adapterRoutes (fastify, _opts) {
  // Public: list adapters
  fastify.get('/adapters', async (_request, reply) => {
    return reply.code(200).send({ adapters: ADAPTERS })
  })

  // Protected: run a specific adapter
  fastify.post('/adapters/:id/run', {
    onRequest: [fastify.authenticate],
    config: { rateLimit: { max: 30, timeWindow: '1 minute' } }
  }, async (request, reply) => {
    const { id } = request.params
    const user = request.user

    // 1. Check that the adapter exists
    const adapter = ADAPTERS.find((a) => a.id === id)
    if (!adapter) {
      return reply.code(404).send({
        statusCode: 404,
        error: 'Not Found',
        code: 'ADAPTER_NOT_FOUND',
        message: `Adapter '${id}' not found`
      })
    }

    // 2. Derive required permission: adapter:run:<id>
    //    A permission of adapter:run:* also satisfies this.
    const requiredPerm = `adapter:run:${id}`

    // 3. Tenant comes from the JWT; routes accept the caller's own tenantId.
    const requiredTenantId = user.tenantId

    // 4. Permission check
    const { allowed, reason } = fastify.checkPermission(user, requiredPerm, requiredTenantId)

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

    // 5. Execute (stub – delegate to the Python layer in production)
    return reply.code(202).send({
      status: 'accepted',
      adapterId: id,
      tenantId: requiredTenantId,
      message: `Adapter '${id}' run queued`
    })
  })
}

module.exports = adapterRoutes
