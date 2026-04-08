const ADAPTERS = ['shodan', 'censys', 'virustotal'];

async function adapterRoutes(fastify) {
  fastify.get('/adapters', async () => ({ items: ADAPTERS }));

  fastify.post(
    '/adapters/:id/run',
    {
      preHandler: [fastify.authenticate, fastify.checkPermission('adapter:run:*')]
    },
    async (request, reply) => {
      const adapterId = request.params.id;
      const target = request.body?.target;
      if (!ADAPTERS.includes(adapterId)) {
        return reply.code(404).send({ error: 'NOT_FOUND', code: 'ADAPTER_UNKNOWN' });
      }
      return reply.send({
        status: 'queued',
        adapter: adapterId,
        target,
        tenantId: request.user.tenantId
      });
    }
  );
}

module.exports = adapterRoutes;
