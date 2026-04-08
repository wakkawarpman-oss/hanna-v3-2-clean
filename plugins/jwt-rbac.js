const fp = require('fastify-plugin');
const crypto = require('crypto');

function parsePermission(permission) {
  const [resource = '*', action = '*', scope = '*'] = String(permission || '').split(':');
  return { resource, action, scope };
}

function permissionMatches(granted, required) {
  const g = parsePermission(granted);
  const r = parsePermission(required);
  return (
    (g.resource === '*' || g.resource === r.resource) &&
    (g.action === '*' || g.action === r.action) &&
    (g.scope === '*' || g.scope === r.scope)
  );
}

function deriveRolePermissions(roles) {
  const matrix = {
    analyst: ['adapter:run:*', 'evidence:read:*'],
    tenant_admin: ['user:list:*', 'config:write:*'],
    superadmin: ['*:*:*']
  };
  return roles.flatMap((role) => matrix[role] || []);
}

async function jwtRbacPlugin(fastify) {
  await fastify.register(require('@fastify/jwt'), {
    secret: process.env.JWT_SECRET || 'dev-secret',
    sign: { expiresIn: '15m' }
  });

  fastify.decorate('authenticate', async function authenticate(request, reply) {
    try {
      await request.jwtVerify();
    } catch (_err) {
      return reply.code(401).send({
        error: 'UNAUTHORIZED',
        code: 'AUTH_INVALID_TOKEN'
      });
    }
  });

  fastify.decorate('issueToken', function issueToken(user) {
    return fastify.jwt.sign({
      sub: String(user.id),
      roles: user.roles || [],
      permissions: user.permissions || [],
      tenantId: String(user.tenantId),
      jti: crypto.randomUUID()
    });
  });

  fastify.decorate('checkPermission', function checkPermission(requiredPermission) {
    return async function permissionGuard(request, reply) {
      const user = request.user || {};
      const explicit = user.permissions || [];
      const implicit = deriveRolePermissions(user.roles || []);
      const effective = [...new Set([...implicit, ...explicit])];

      const isSuperadmin = effective.some((perm) => perm === '*:*:*');
      if (!isSuperadmin) {
        const tokenTenant = String(user.tenantId || '');
        const reqTenant = String(
          request.params?.tenantId || request.body?.tenantId || tokenTenant
        );
        if (!tokenTenant || (reqTenant && tokenTenant !== reqTenant)) {
          return reply.code(403).send({
            error: 'FORBIDDEN',
            code: 'RBAC_TENANT_MISMATCH',
            required: requiredPermission
          });
        }
      }

      const allowed = effective.some((perm) => permissionMatches(perm, requiredPermission));
      if (!allowed) {
        return reply.code(403).send({
          error: 'FORBIDDEN',
          code: 'RBAC_PERMISSION_DENIED',
          required: requiredPermission
        });
      }
    };
  });
}

module.exports = fp(jwtRbacPlugin);
