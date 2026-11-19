import { test, expect, login, logout, ready, restartAndLogin, screen, type App, type State } from '../fixtures.js';
import type { Page } from '@playwright/test';
async function connectors(page: Page) { return (await (await page.request.get('/operator/v1/local-connectors')).json()).items as Array<Record<string, any>>; }
async function add(page: Page, app: App, kind = 'ollama', name = 'Browser local server', key = '') {
  await screen(page, 'Local Connectors');
  await page.getByRole('button', { name: 'Add local connector', exact: true }).click();
  await page.getByLabel('Connection name', { exact: true }).fill(name);
  await page.getByRole('combobox', { name: 'Server type', exact: true }).selectOption(kind);
  await page.getByLabel('Server URL', { exact: true }).fill(app.inventoryOrigin);
  if (key) await page.getByLabel('API key · optional', { exact: true }).fill(key);
  await page.getByRole('button', { name: 'Connect and discover models', exact: true }).click();
  await expect(page.getByRole('heading', { name: kind === 'ollama' ? 'Installed models' : 'Available models', exact: true })).toBeVisible();
  return (await connectors(page)).find(item => item.display_name === name)!;
}
test.beforeEach(async ({ page, app }) => { await login(page, app); await ready(page); });
test('new profiles have an honest empty state', async ({ page }) => {
  await screen(page, 'Local Connectors'); await expect(page.locator('#view-content')).toContainText('No local connectors yet');
});
test('Ollama discovery displays exact IDs and loaded-model metadata', async ({ page, app }) => {
  const item = await add(page, app);
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'browser.text.v1' })).toContainText('Loaded');
  expect(item.enabled).toBe(false); expect(item.selected_models).toEqual([]);
  expect((await app.command<State>('state')).metadata_requests).toContain('/api/tags');
});
test('OpenAI-compatible discovery uses its supported metadata endpoint', async ({ page, app }) => {
  await add(page, app, 'openai_compatible');
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeVisible();
  expect((await app.command<State>('state')).metadata_requests).toContain('/v1/models');
});
test('selection is required before enabling and survives reload', async ({ page, app }) => {
  await add(page, app); await expect(page.getByRole('button', { name: 'Enable selected models', exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true }).check();
  await page.getByRole('button', { name: 'Enable selected models', exact: true }).click();
  await expect(page.locator('#view-message')).toContainText('Connector enabled');
  await page.reload(); await ready(page);
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeChecked();
  expect((await connectors(page))[0]).toMatchObject({ enabled: true, selected_models: ['browser.text.v1'] });
});
test('a saved connector can be disabled without deleting its inventory', async ({ page, app }) => {
  await add(page, app); await page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true }).check();
  await page.getByRole('button', { name: 'Enable selected models', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Disable connector', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Disable connector', exact: true }).click();
  await expect(page.locator('#view-message')).toContainText('Connector disabled');
  expect((await connectors(page))[0].discovery.models).toHaveLength(1);
});
test('saved API keys are never exposed and empty edits keep the existing key', async ({ page, app }) => {
  const key = 'synthetic-browser-connector-key-000000'; const item = await add(page, app, 'ollama', 'Keyed server', key);
  const detail = await page.request.get('/operator/v1/local-connectors/' + item.connector_id);
  expect(await detail.text()).not.toContain(key);
  await page.getByRole('button', { name: 'Edit connector', exact: true }).click();
  await expect(page.getByLabel('API key · leave blank to keep the saved key', { exact: true })).toBeEmpty();
  await page.getByLabel('Connection name', { exact: true }).fill('Renamed keyed server');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Edit connector', exact: true })).toBeVisible();
  expect((await connectors(page))[0]).toMatchObject({ display_name: 'Renamed keyed server', credential_present: true });
});
test('empty inventories cannot be enabled', async ({ page, app }) => {
  await app.command('inventory_mode', { mode: 'empty' }); await add(page, app);
  await expect(page.locator('#view-content')).toContainText('No models were returned');
  await expect(page.getByRole('button', { name: 'Enable selected models', exact: true })).toBeDisabled();
});
test('authentication errors preserve a saved connector and show a safe explanation', async ({ page, app }) => {
  await app.command('inventory_mode', { mode: 'auth' }); const saved = await add(page, app);
  await expect(page.locator('#view-message')).toContainText('Model discovery was not confirmed');
  await expect(page.locator('#view-message')).toHaveClass(/error/);
  await expect(page.locator('#view-content')).not.toContainText('Synthetic private provider detail');
  expect(saved.discovery).toMatchObject({ state: 'failed', reason: 'SERVER_AUTHENTICATION_REQUIRED' });
  expect(saved.enabled).toBe(false);
  await app.command('inventory_mode', { mode: 'ready' });
  await page.getByRole('button', { name: 'Discover models', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeVisible();
  const recovered = await connectors(page);
  expect(recovered).toHaveLength(1); expect(recovered[0].connector_id).toBe(saved.connector_id);
  expect(recovered[0].discovery.state).toBe('observed');
});
test('invalid inventories remain unavailable for model selection', async ({ page, app }) => {
  await app.command('inventory_mode', { mode: 'invalid' }); await add(page, app);
  await expect(page.getByRole('button', { name: 'Enable selected models', exact: true })).toBeDisabled();
  expect((await connectors(page))[0].enabled).toBe(false);
});
for (const [kind, url] of [['public', 'https://203.0.113.10'], ['credential-bearing', 'http://synthetic:fixture@127.0.0.1']]) {
  test(kind + ' URLs are rejected without saving', async ({ page }) => {
    await screen(page, 'Local Connectors'); await page.getByRole('button', { name: 'Add local connector', exact: true }).click();
    await page.getByLabel('Connection name', { exact: true }).fill('Unsafe address');
    await page.getByLabel('Server URL', { exact: true }).fill(url);
    await page.getByRole('button', { name: 'Connect and discover models', exact: true }).click();
    await expect(page.locator('#view-content [role=alert]')).not.toBeEmpty();
    expect(await connectors(page)).toHaveLength(0);
  });
}
test('connector deletion is confirmed and leaves the model server untouched', async ({ page, app }) => {
  await add(page, app); page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Delete connector', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Local servers and containers', exact: true })).toBeVisible();
  expect(await connectors(page)).toHaveLength(0);
  expect((await app.command<State>('state')).inference_requests).toBe(0);
});
test('read-only operators can inspect saved inventory but cannot discover or edit', async ({ page, app }) => {
  await add(page, app); await logout(page);
  await login(page, app, 'reader', app.userPassword); await ready(page); await screen(page, 'Local Connectors');
  await page.getByRole('button', { name: 'Models', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Installed models', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Discover models', exact: true })).toHaveCount(0);
});
test('auto-check can be paused and search survives a manual check', async ({ page, app }) => {
  await add(page, app); await page.getByRole('button', { name: '← Local Connectors', exact: true }).click();
  await page.getByLabel('Search local connectors', { exact: true }).fill('Browser local');
  await page.getByRole('checkbox', { name: 'Auto-check every 15 seconds', exact: true }).uncheck();
  await page.getByRole('button', { name: 'Check now', exact: true }).click();
  await expect(page.getByLabel('Search local connectors', { exact: true })).toHaveValue('Browser local');
  await expect(page.getByRole('checkbox', { name: 'Auto-check every 15 seconds', exact: true })).not.toBeChecked();
});
test('saved connectors and model choices survive a service restart', async ({ page, app }) => {
  await add(page, app); await page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true }).check();
  await page.getByRole('button', { name: 'Enable selected models', exact: true }).click();
  await expect(page.locator('#view-message')).toContainText('Connector enabled');
  await restartAndLogin(page, app); await screen(page, 'Local Connectors');
  await page.getByRole('button', { name: 'Models', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'Select browser.text.v1', exact: true })).toBeChecked();
});
