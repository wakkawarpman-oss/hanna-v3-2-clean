'use strict'

const fp = require('fastify-plugin')
const fastifyJwt = require('@fastify/jwt')

/**
 * Parse a permission string into its parts.
 * Format: resource:action:scope
 * @param {string} perm
 * @returns {{ resource: string, action: string, scope: string }}
 */
function parsePerm (perm) {
  const [resource = '*', action = '*', scope = '*'] = perm.split(':')
  return { resource, action, scope }
}

/**
 * Return true if `candidate` matches `pattern` where '*' is a wildcard segment.
 * @param {string} pattern
 * @param {string} candidate
 * @returns {boolean}
 */
function segmentMatch (pattern, candidate) {
  return pattern === '*' || pattern === candidate
}

/**
 * Check whether a flat permission string grants the required permission.
 * Supports wildcard '*' in any segment.
 * @param {string} granted  – e.g. "adapter:run:*"
 * @param {string} required – e.g. "adapter:run:shodan"
 * @returns {boolean}
 */
function permissionMatches (granted, required) {
  const g = parsePerm(granted)
  const r = parsePerm(required)
  return (
    segmentMatch(g.resource, r.resource) &&
    segmentMatch(g.action, r.action) &&
    segmentMatch(g.scope, r.scope)
  )
}

/**
 * Determine whether the decoded JWT payload grants the required permission.
 *
 * Rules (evaluated in order):
 *   1. Deny by default.
 *   2. *:*:* (superadmin) bypasses all checks.
 *   3. Tenant boundary must match (payload.tenantId === requiredTenantId).
 *   4. Explicit permissions (payload.permissions[]) are evaluated first.
 *   5. Role-derived permissions are not used in this slice
 *      (extension point: look up role→permission map here).
 *
 * @param {object} payload         – decoded JWT payload
 * @param {string} requiredPerm    – e.g. "adapter:run:shodan"
 * @param {string} requiredTenantId
 * @returns {{ allowed: boolean, reason: string }}
 */
function checkPermission (payload, requiredPerm, requiredTenantId) {
  const permissions = Array.isArray(payload.permissions) ? payload.permissions : []

  // Superadmin bypass
  if (permissions.includes('*:*:*')) {
    return { allowed: true, reason: 'superadmin' }
  }

  // Tenant boundary
  if (payload.tenantId !== requiredTenantId) {
    return { allowed: false, reason: 'tenant_mismatch' }
  }

  // Explicit permission match (wildcard-aware)
  const granted = permissions.some((p) => permissionMatches(p, requiredPerm))
  if (granted) {
    return { allowed: true, reason: 'explicit_permission' }
  }

  return { allowed: false, reason: 'insufficient_permission' }
}

/**
 * Fastify plugin: registers @fastify/jwt and decorates the instance with
 * request.authenticate() and fastify.checkPermission().
 */
async function jwtRbacPlugin (fastify, opts) {
  const jwtSecret = opts.jwtSecret || process.env.JWT_SECRET

  if (!jwtSecret) {
    throw new Error(
      'JWT_SECRET is required. ' +
      'Pass jwtSecret in plugin options or set the JWT_SECRET environment variable.'
    )
  }

  await fastify.register(fastifyJwt, { secret: jwtSecret })

  // Decorate fastify with authenticate() – verifies the Bearer token and
  // populates request.user with the decoded payload.
  // Usage: onRequest: [fastify.authenticate]  OR  await request.jwtVerify()
  fastify.decorate('authenticate', async function (request, reply) {
    try {
      await request.jwtVerify()
    } catch (err) {
      reply.code(401).send({
        statusCode: 401,
        error: 'Unauthorized',
        code: 'AUTH_INVALID_OR_EXPIRED_TOKEN',
        message: 'Invalid or expired token'
      })
    }
  })

  // Expose permission checker on the fastify instance so routes can call it.
  fastify.decorate('checkPermission', checkPermission)
}

module.exports = fp(jwtRbacPlugin, { name: 'jwt-rbac' })
module.exports.checkPermission = checkPermission
module.exports.permissionMatches = permissionMatches
