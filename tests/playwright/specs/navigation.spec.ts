import { test, expect, login, ready, screen, api, type State } from '../fixtures.js';

const views = ['Overview', 'Activity', 'Usage & Costs', 'External accounting', 'External Providers',
  'Local Connectors', 'Private Hosting', 'Office Labs', 'All Models', 'Users & Permissions',
  'Connections & Credentials', 'Configuration', 'Build & context'];
for (const view of views) {
  test('administrator can open ' + view, async ({ page, app }) => {
    await login(page, app); await ready(page); await screen(page, view);
    await expect(page.locator('#view-title')).not.toBeEmpty();
    await expect(page).toHaveTitle(/ · EzLLMRouter$/);
    await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toHaveCount(0);
    await expect(page.locator('#view-title')).toBeFocused();
    expect((await app.command<State>('state')).submissions).toBe(3);
  });
}
test('deep links and back/forward navigation retain the selected screen', async ({ page, app }) => {
  await login(page, app, 'admin', app.adminPassword, '/#/users'); await ready(page);
  await expect(page.locator('#view-title')).toHaveText('Users & Permissions');
  await screen(page, 'All Models'); await screen(page, 'Local Connectors');
  await page.goBack(); await expect(page.locator('#view-title')).toHaveText('All Models'); await ready(page);
  await page.goForward(); await expect(page.locator('#view-title')).toHaveText('Local Connectors');
});
test('keyboard users can skip navigation to the active heading', async ({ page, app }) => {
  await login(page, app); await ready(page);
  await page.locator('#skip-link').focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#view-title')).toBeFocused();
});
test('a narrow viewport keeps sign-in, navigation and forms operable', async ({ page, app }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, app); await ready(page); await screen(page, 'Users & Permissions');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.getByLabel('Full name', { exact: true })).toBeVisible();
  await expect(page.getByLabel(/^Username ·/)).toBeFocused();
});
test('transient API errors offer a working retry', async ({ page, app }) => {
  await login(page, app); await ready(page);
  let fail = true;
  await page.route('**/operator/v1/models', route => fail
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'METADATA_UNAVAILABLE' }) })
    : route.continue());
  await screen(page, 'All Models');
  await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toBeVisible();
  fail = false; await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('#view-content').getByRole('heading', { name: 'All Models', exact: true })).toBeVisible();
});
test('late results from a previous screen cannot replace the current screen', async ({ page, app }) => {
  await login(page, app); await ready(page);
  let release!: () => void, started!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/operator/v1/models', async route => { started(); await waiting; await route.continue(); });
  await page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button', { name: 'All Models', exact: true }).click();
  await requested; await expect(page.locator('#view-content')).toHaveAttribute('aria-busy', 'true');
  await screen(page, 'Users & Permissions'); release();
  await expect(page.getByRole('heading', { name: 'User accounts', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'All Models', exact: true })).toHaveCount(0);
});

test.describe('accounting-only profile', () => {
  test.use({ appOptions: { integrationOnly: true } });
  test('the accounting entry point restores its route after reload', async ({ page, app }) => {
    await login(page, app, 'admin', app.adminPassword, '/integration#/accounting?source=external&dataset_id=dataset.synthetic.v2'); await ready(page);
    await expect(page.locator('#view-title')).toContainText('Accounting');
    await page.reload(); await ready(page); await expect(page.locator('#view-title')).toContainText('Accounting');
    await expect(page.getByRole('button', { name: 'Configuration', exact: true })).toHaveCount(0);
    expect((await api(page, 'POST', '/operator/v1/demos', { kind: 'text' })).status()).toBe(404);
  });
});
