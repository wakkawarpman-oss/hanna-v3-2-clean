'use strict'

const fastify = require('fastify')
const rateLimit = require('@fastify/rate-limit')
const jwtRbac = require('./plugins/jwt-rbac')
const authRoutes = require('./routes/auth')
const adapterRoutes = require('./routes/adapters')

const ROUTE_LOADERS = {
  users: () => require('./routes/users'),
  reports: () => require('./routes/reports'),
  metrics: () => require('./routes/metrics')
}

async function lazyLoadRoutes (app, routeNames = ['users', 'reports', 'metrics']) {
  if (!app.hasDecorator('loadedRouteNames')) {
    app.decorate('loadedRouteNames', new Set())
  }

  for (const name of routeNames) {
    if (app.loadedRouteNames.has(name)) continue

    const loader = ROUTE_LOADERS[name]
    if (!loader) continue

    await app.register(loader())
    app.loadedRouteNames.add(name)
  }
}

async function buildOptimizedApp (opts = {}) {
  const { jwtSecret, lazyRoutes = true, ...fastifyOpts } = opts
  const app = fastify(fastifyOpts)

  await app.register(rateLimit, { global: false })
  await app.register(jwtRbac, { jwtSecret })

  await app.register(authRoutes)
  await app.register(adapterRoutes)

  if (lazyRoutes) {
    await lazyLoadRoutes(app)
  }

  return app
}

module.exports = {
  buildOptimizedApp,
  lazyLoadRoutes
}

if (require.main === module) {
  buildOptimizedApp({ logger: true })
    .then((app) => app.listen({ port: 3000, host: '0.0.0.0' }))
    .then(() => console.log('HANNA optimized app listening on port 3000'))
    .catch((err) => {
      console.error(err)
      process.exit(1)
    })
}
