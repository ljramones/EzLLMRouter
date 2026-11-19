import { test, expect, login, ready, screen, api, createUser, type State } from '../fixtures.js';

test('unauthenticated browsers cannot read protected API data', async ({ page }) => {
  await page.goto('/');
  for (const endpoint of ['users', 'models', 'principals', 'activity', 'local-connectors', 'integration/datasets']) {
    expect((await page.request.get('/operator/v1/' + endpoint)).status(), endpoint).toBe(401);
  }
});
test('read-only accounts can inspect models and connectors but cannot manage users', async ({ page, app }) => {
  await login(page, app, 'reader', app.userPassword); await ready(page);
  await screen(page, 'All Models'); await expect(page.getByRole('button', { name: 'Add model', exact: true })).toHaveCount(0);
  await screen(page, 'Local Connectors'); await expect(page.getByRole('button', { name: 'Add local connector', exact: true })).toHaveCount(0);
  await screen(page, 'Users & Permissions'); await expect(page.getByRole('heading', { name: 'Your account', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create user', exact: true })).toHaveCount(0);
  expect((await page.request.get('/operator/v1/users')).status()).toBe(403);
  expect((await api(page, 'POST', '/operator/v1/users', {})).status()).toBe(403);
  expect((await api(page, 'POST', '/operator/v1/local-connectors', {})).status()).toBe(403);
});
test('ordinary users have no administrative navigation or direct API access', async ({ page, app }) => {
  await login(page, app, 'member', app.userPassword); await ready(page);
  for (const name of ['Local Connectors', 'External Providers', 'Configuration', 'Build & context'])
    await expect(page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button', { name, exact: true })).toHaveCount(0);
  for (const path of ['/operator/v1/users', '/operator/v1/local-connectors', '/operator/v1/integration/datasets'])
    expect((await page.request.get(path)).status()).toBe(403);
});
test('ordinary activity and usage remain scoped to their own identity', async ({ page, app }) => {
  await login(page, app, 'member', app.userPassword); await ready(page); await screen(page, 'Activity');
  const result = await (await page.request.get('/operator/v1/activity')).json();
  expect(result.items).toHaveLength(1); expect(result.items[0].principal_id).toBe(app.users.member);
  await expect(page.locator('#view-content')).toContainText('submission.browser.1');
  await expect(page.locator('#view-content')).not.toContainText('submission.browser.2');
  const attempt = await page.request.get('/operator/v1/activity/submission.browser.3');
  expect([403, 404]).toContain(attempt.status());
});
test('mutations reject missing CSRF before parsing a body', async ({ page, app }) => {
  await login(page, app); await ready(page);
  const response = await page.request.post('/operator/v1/users', {
    headers: { Origin: app.origin, 'Content-Type': 'application/json' }, data: '{invalid-json',
  });
  expect(response.status()).toBe(403); expect((await response.json()).error).toBe('CSRF_REJECTED');
});
test('mutations reject foreign origins even with a valid CSRF token', async ({ page, app }) => {
  await login(page, app); await ready(page);
  const response = await api(page, 'POST', '/operator/v1/users', {}, { Origin: 'https://foreign.invalid' });
  expect(response.status()).toBe(403); expect((await response.json()).error).toBe('ORIGIN_REJECTED');
});
test('secret account values are not returned by user listing', async ({ page, app }) => {
  await login(page, app); await ready(page);
  const response = await page.request.get('/operator/v1/users'); const text = await response.text();
  expect(text).not.toContain(app.adminPassword); expect(text).not.toContain(app.userPassword);
  expect(text).not.toContain('scrypt$');
});
test('user-controlled display names render as text', async ({ page, app }) => {
  await login(page, app); await ready(page); const record = await createUser(page, 'literal.browser');
  const label = '<img src=x onerror="window.browserInjected=true">';
  expect((await api(page, 'POST', '/operator/v1/users/' + record.principal_id, {
    username: record.username, display_name: label, role: record.role, status: record.status, expected_revision: record.revision,
  })).ok()).toBeTruthy();
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('cell', { name: label, exact: true })).toBeVisible();
  await expect(page.locator('#view-content img')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).browserInjected)).toBeUndefined();
});
test('assets and API responses carry browser security headers', async ({ page, app }) => {
  const response = await page.goto('/');
  expect(response?.headers()['content-security-policy']).toContain("frame-ancestors 'none'");
  expect(response?.headers()['x-content-type-options']).toBe('nosniff');
  await login(page, app); await ready(page);
  const session = await page.request.get('/operator/v1/session');
  expect(session.headers()['cache-control']).toContain('no-store');
});
test('normal navigation never launches model work', async ({ page, app }) => {
  await login(page, app); await ready(page);
  for (const name of ['All Models', 'Users & Permissions', 'Activity', 'Usage & Costs', 'External Providers']) await screen(page, name);
  const state = await app.command<State>('state');
  expect(state).toMatchObject({ submissions: 3, execution_calls: 0, inference_requests: 0 });
});
