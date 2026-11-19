import { test, expect, login, ready, restartAndLogin, screen, type State } from '../fixtures.js';
import type { Page } from '@playwright/test';
async function connection(page: Page) { return (await (await page.request.get('/operator/v1/connections/conn.browser')).json()).connection; }
async function create(page: Page) {
  await screen(page, 'External Providers');
  await page.getByRole('button', { name: 'Add provider', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByLabel('API setup name (for example, Production or Testing)', { exact: true }).fill('Browser API setup');
  await page.getByLabel('Advanced · stable setup ID (conn.…)', { exact: true }).fill('conn.browser');
  await page.getByRole('combobox', { name: 'Funding / environment', exact: true }).selectOption('controlled');
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.locator('#view-title')).toHaveText('Browser API setup'); await ready(page);
}
async function setKey(page: Page, secret: string) {
  await page.getByRole('button', { name: /^(Set up API access|Replace key)$/, exact: true }).click();
  await page.getByLabel('Outbound API credential (write only)', { exact: true }).fill(secret);
  await expect(page.getByRole('checkbox', { name: /^Save and test API access/ })).not.toBeChecked();
  await page.getByRole('button', { name: 'Save API credential', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Replace key', exact: true })).toBeVisible();
}
test.beforeEach(async ({ page, app }) => { await login(page, app); await ready(page); });
test('provider adapters are explicitly selected before configuration', async ({ page }) => {
  await screen(page, 'External Providers'); await page.getByRole('button', { name: 'Add provider', exact: true }).click();
  const choices = page.getByRole('combobox', { name: 'Versioned API adapter', exact: true });
  for (const name of ['OpenAI', 'Anthropic', 'Google Gemini', 'vLLM', 'xAI', 'DeepSeek']) await expect(choices).toContainText(name);
});
test('creating a draft neither saves a key nor enables inference', async ({ page, app }) => {
  await create(page); const record = await connection(page);
  expect(record.credential_state).not.toBe('present');
  await expect(page.locator('#view-content')).toContainText('Not stored');
  expect((await app.command<State>('state')).inference_requests).toBe(0);
});
test('saving and replacing keys keeps them write-only and does not contact providers', async ({ page, app }) => {
  await create(page); const first = 'sk-browser-fixture-first-000000000000000000';
  await setKey(page, first); const before = await connection(page);
  await setKey(page, 'sk-browser-fixture-second-000000000000000000'); const after = await connection(page);
  expect(after.credential_version).toBeGreaterThan(before.credential_version);
  const raw = await (await page.request.get('/operator/v1/connections/conn.browser')).text();
  expect(raw).not.toContain(first); expect(raw).not.toContain('sk-browser-fixture-second');
  await expect(page.locator('#view-content')).not.toContainText(first);
  expect((await app.command<State>('state')).execution_calls).toBe(0);
});
test('removing a credential requires confirmation and clears readiness', async ({ page }) => {
  await create(page); await setKey(page, 'sk-browser-fixture-delete-000000000000000000');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Remove key', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Set up API access', exact: true })).toBeVisible();
  expect((await connection(page)).credential_state).not.toBe('present');
});
for (const tab of ['API setup', 'Models', 'Usage & Costs', 'Connection & Credentials', 'Health', 'History']) {
  test('a saved setup opens its ' + tab + ' section without implicit provider calls', async ({ page, app }) => {
    await create(page);
    await page.locator('#view-content').getByRole('button', { name: tab, exact: true }).click(); await ready(page);
    await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toHaveCount(0);
    expect((await app.command<State>('state')).inference_requests).toBe(0);
  });
}
test('stored provider setup and encrypted credentials survive restart', async ({ page, app }) => {
  await create(page); await setKey(page, 'sk-browser-fixture-restart-000000000000000000');
  const hash = new URL(page.url()).hash;
  await restartAndLogin(page, app, '/' + hash);
  await expect(page.getByRole('button', { name: 'Replace key', exact: true })).toBeVisible();
  expect((await connection(page)).credential_state).toBe('present');
});
