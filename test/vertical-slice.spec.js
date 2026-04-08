const t = require('tap');
const { buildApp } = require('../app');

async function login(app, username, password = 'pass') {
  const res = await app.inject({
    method: 'POST',
    url: '/api/auth/login',
    payload: { username, password }
  });
  return res;
}

t.test('vertical slice: login success returns access token', async (t) => {
  const app = buildApp();
  t.teardown(() => app.close());

  const res = await login(app, 'analyst1');
  t.equal(res.statusCode, 200);
  const body = res.json();
  t.ok(body.access_token);
});

t.test('vertical slice: protected route succeeds with required permission', async (t) => {
  const app = buildApp();
  t.teardown(() => app.close());

  const auth = await login(app, 'analyst1');
  const token = auth.json().access_token;

  const res = await app.inject({
    method: 'POST',
    url: '/api/adapters/shodan/run',
    headers: { authorization: `Bearer ${token}` },
    payload: { target: 'example.com', tenantId: 'tenant1' }
  });

  t.equal(res.statusCode, 200);
  t.equal(res.json().status, 'queued');
});

t.test('vertical slice: deny without permission and deny tenant mismatch', async (t) => {
  const app = buildApp();
  t.teardown(() => app.close());

  const viewerAuth = await login(app, 'viewer1');
  const viewerToken = viewerAuth.json().access_token;

  const deniedByPermission = await app.inject({
    method: 'POST',
    url: '/api/adapters/shodan/run',
    headers: { authorization: `Bearer ${viewerToken}` },
    payload: { target: 'example.com', tenantId: 'tenant1' }
  });

  t.equal(deniedByPermission.statusCode, 403);
  t.equal(deniedByPermission.json().code, 'RBAC_PERMISSION_DENIED');

  const analystAuth = await login(app, 'analyst1');
  const analystToken = analystAuth.json().access_token;

  const deniedByTenant = await app.inject({
    method: 'POST',
    url: '/api/adapters/shodan/run',
    headers: { authorization: `Bearer ${analystToken}` },
    payload: { target: 'example.com', tenantId: 'tenant2' }
  });

  t.equal(deniedByTenant.statusCode, 403);
  t.equal(deniedByTenant.json().code, 'RBAC_TENANT_MISMATCH');
});
