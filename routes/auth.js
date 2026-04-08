const USERS = {
  analyst1: {
    id: 'user-analyst-1',
    username: 'analyst1',
    password: 'pass',
    roles: ['analyst'],
    permissions: ['adapter:run:*', 'evidence:read:tenant1'],
    tenantId: 'tenant1'
  },
  viewer1: {
    id: 'user-viewer-1',
    username: 'viewer1',
    password: 'pass',
    roles: ['viewer'],
    permissions: ['evidence:read:tenant1'],
    tenantId: 'tenant1'
  },
  root1: {
    id: 'user-root-1',
    username: 'root1',
    password: 'pass',
    roles: ['superadmin'],
    permissions: ['*:*:*'],
    tenantId: 'tenantX'
  }
};

function findUser(username) {
  return USERS[username] || null;
}

function validPassword(password, expected) {
  return String(password || '') === String(expected || '');
}

async function authRoutes(fastify) {
  fastify.post('/login', async (request, reply) => {
    const { username, password } = request.body || {};
    const user = findUser(username);

    if (!user || !validPassword(password, user.password)) {
      return reply.code(401).send({
        error: 'UNAUTHORIZED',
        code: 'AUTH_INVALID_CREDENTIALS'
      });
    }

    const accessToken = fastify.issueToken(user);
    return reply.send({ access_token: accessToken });
  });
}

module.exports = authRoutes;
