'use strict'

const fastify = require('fastify')
const rateLimit = require('@fastify/rate-limit')
const jwtRbac = require('./plugins/jwt-rbac')
const authRoutes = require('./routes/auth')
const adapterRoutes = require('./routes/adapters')

/**
 * Build the Fastify application.
 *
 * Accepts an opts object so the same factory is usable in tests
 * (with logger: false) and in production (with logger: true).
 *
 * @param {import('fastify').FastifyServerOptions} opts
 * @returns {Promise<import('fastify').FastifyInstance>}
 */
async function buildApp (opts = {}) {
  const { jwtSecret, ...fastifyOpts } = opts
  const app = fastify(fastifyOpts)

  // 1. Plugins (must be registered before routes that depend on them)
  await app.register(rateLimit, { global: false })
  await app.register(jwtRbac, { jwtSecret })

  // 2. Routes
  await app.register(authRoutes)
  await app.register(adapterRoutes)

  return app
}

module.exports = { buildApp }

// Allow running directly: `node app.js`
if (require.main === module) {
  buildApp({ logger: true })
    .then((app) => app.listen({ port: 3000, host: '0.0.0.0' }))
    .then(() => console.log('HANNA Fastify auth service listening on port 3000'))
    .catch((err) => {
      console.error(err)
      process.exit(1)
    })
}
