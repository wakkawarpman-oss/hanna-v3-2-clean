const Fastify = require('fastify');
const jwtRbacPlugin = require('./plugins/jwt-rbac');
const authRoutes = require('./routes/auth');
const adapterRoutes = require('./routes/adapters');

function buildApp() {
  const app = Fastify({ logger: false });

  app.register(jwtRbacPlugin);
  app.register(authRoutes, { prefix: '/api/auth' });
  app.register(adapterRoutes, { prefix: '/api' });

  app.get('/health', async () => ({ ok: true }));

  return app;
}

module.exports = { buildApp };

if (require.main === module) {
  const app = buildApp();
  const port = Number(process.env.PORT || 3000);
  app.listen({ port, host: '0.0.0.0' }).catch((err) => {
    app.log.error(err);
    process.exit(1);
  });
}
