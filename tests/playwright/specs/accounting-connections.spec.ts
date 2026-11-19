import { test, expect, login, logout, ready, restartAndLogin, type State } from '../fixtures.js';
import type { Page } from '@playwright/test';

const location = '/integration#/connections?connection_dataset_id=dataset.synthetic.v2';
const endpoint = '/operator/v1/integration/connections?dataset_id=dataset.synthetic.v2';
const secret = 'sk-browser-accounting-fixture-0000000000000000';
type Connection = { account_id: string; state: string; revision: number; selected_version: number; selected_models: string[]; allowed_operations: string[] };
async function record(page: Page): Promise<Connection> {
  const response = await page.request.get(endpoint); expect(response.ok()).toBeTruthy();
  return (await response.json()).items[0];
}
async function add(page: Page, provider = 'openai', key = secret) {
  await page.getByRole('button', { name: 'Add external provider', exact: true }).click();
  await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption(provider);
  await page.getByLabel('API key', { exact: true }).fill(key);
  await page.getByLabel('Friendly name', { exact: true }).fill('Browser external provider');
  await page.getByRole('button', { name: 'Connect and discover models', exact: true }).click();
  await expect(page.locator('.connection-editor')).toBeVisible();
}
async function save(page: Page) {
  await page.getByRole('checkbox', { name: /Browser text model/ }).check();
  await page.getByRole('button', { name: 'Save model choices', exact: true }).click();
  await expect(page.locator('.connection-row')).toContainText('Connected');
}
async function manage(page: Page) {
  await page.getByRole('button', { name: 'Manage', exact: true }).click();
  await expect(page.locator('.connection-editor')).toBeVisible();
}
async function replace(page: Page, key: string) {
  await page.getByRole('button', { name: 'Change API key', exact: true }).click();
  await page.getByLabel('New API key', { exact: true }).fill(key);
  await page.getByRole('button', { name: 'Validate and save', exact: true }).click();
}

test.use({ appOptions: { integrationOnly: true } });
test.beforeEach(async ({ page, app }) => { await login(page, app, 'admin', app.adminPassword, location); await ready(page); });

test('a fresh collection has no configured external providers', async ({ page, app }) => {
  await expect(page.locator('#view-content')).toContainText('No ordinary provider connections in this collection');
  expect((await app.command<State>('state')).credential_metadata_probes).toBe(0);
});
test('external provider choices are explicit and local servers have their own page', async ({ page }) => {
  await page.getByRole('button', { name: 'Add external provider', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Provider', exact: true }).locator('option')).toHaveText(['OpenAI', 'Anthropic', 'xAI']);
  await expect(page.locator('#view-content')).toContainText('Local Connectors');
  await expect(page.getByLabel('API key', { exact: true })).toHaveAttribute('type', 'password');
});
test('discovery keeps the encrypted key write-only and waits for model choices', async ({ page, app }) => {
  await add(page);
  await expect(page.locator('.connection-state')).toHaveText('Awaiting selection');
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).not.toBeChecked();
  expect(await record(page)).toMatchObject({ state: 'pending', selected_version: 0, selected_models: [] });
  expect(await (await page.request.get(endpoint)).text()).not.toContain(secret);
  await expect(page.locator('#view-content')).not.toContainText(secret);
  expect((await app.command<State>('state')).credential_metadata_probes).toBe(1);
});
test('saved model choices and account identity survive reload', async ({ page }) => {
  await add(page, 'anthropic'); await save(page); const saved = await record(page);
  expect(saved).toMatchObject({ state: 'connected', selected_version: 1, selected_models: ['browser.text.v1'] });
  await page.reload(); await ready(page); await manage(page);
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
  expect((await record(page)).account_id).toBe(saved.account_id);
});
test('model search preserves explicit unsaved selections', async ({ page }) => {
  await add(page); await page.getByRole('checkbox', { name: /Browser text model/ }).check();
  await page.getByLabel('Search discovered models', { exact: true }).fill('does-not-exist');
  await expect(page.locator('.connection-models')).toContainText('No models match this search');
  await page.getByLabel('Search discovered models', { exact: true }).fill('');
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
  expect((await record(page)).selected_models).toEqual([]);
});
test('cancel asks before discarding an unsaved selection', async ({ page }) => {
  await add(page); await page.getByRole('checkbox', { name: /Browser text model/ }).check();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.connection-row')).toContainText('No saved models');
  expect((await record(page)).selected_models).toEqual([]);
});
test('refreshing model metadata retains the unsaved choice', async ({ page, app }) => {
  await add(page); await page.getByRole('checkbox', { name: /Browser text model/ }).check();
  await page.getByText('Connection settings', { exact: true }).click();
  const revision = (await record(page)).revision;
  await page.getByRole('button', { name: 'Refresh models', exact: true }).click();
  await expect.poll(async () => (await record(page)).revision).toBeGreaterThan(revision);
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
  await save(page); expect((await app.command<State>('state')).credential_metadata_probes).toBe(2);
});
test('a rejected credential is reported honestly and can be replaced', async ({ page }) => {
  await add(page, 'openai', 'bad-browser-fixture-key-0000000000000000');
  await expect(page.locator('.connection-editor')).toContainText('The provider rejected the credential');
  await expect(page.getByRole('button', { name: 'Save model choices', exact: true })).toHaveCount(0);
  await replace(page, secret);
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeVisible(); await save(page);
  expect((await record(page)).selected_version).toBe(2);
});
test('an unsuccessful replacement preserves the current credential and policy', async ({ page }) => {
  await add(page); await save(page); await manage(page); const before = await record(page);
  await page.getByText('Connection settings', { exact: true }).click();
  await replace(page, 'bad-browser-replacement-0000000000000000');
  await expect(page.locator('.connection-replace')).toContainText('Replacement not saved');
  await expect(page.getByLabel('New API key', { exact: true })).toBeEmpty();
  expect(await record(page)).toEqual(before);
});
test('a successful replacement advances its version without exposing either key', async ({ page }) => {
  await add(page); await save(page); await manage(page);
  await page.getByText('Connection settings', { exact: true }).click();
  const next = 'sk-browser-accounting-replacement-0000000000'; await replace(page, next);
  await expect.poll(async () => (await record(page)).selected_version).toBe(2);
  const raw = await (await page.request.get(endpoint)).text();
  expect(raw).not.toContain(secret); expect(raw).not.toContain(next);
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
});
test('disabling requires confirmation and prevents further saves', async ({ page }) => {
  await add(page); await save(page); await manage(page);
  await page.getByText('Connection settings', { exact: true }).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Disable connection', exact: true }).click();
  expect((await record(page)).state).toBe('connected');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Disable connection', exact: true }).click();
  await expect(page.locator('.connection-state')).toHaveText('Disabled');
  await expect(page.getByRole('button', { name: 'Save model choices', exact: true })).toBeDisabled();
  expect((await record(page)).state).toBe('disabled');
});
test('encrypted credentials and policy survive an application restart', async ({ page, app }) => {
  await add(page); await save(page); const before = await record(page);
  await restartAndLogin(page, app, location); await manage(page);
  await expect(page.getByRole('checkbox', { name: /Browser text model/ })).toBeChecked();
  expect(await record(page)).toEqual(before);
});
test('speech permissions are selected explicitly for xAI', async ({ page }) => {
  await add(page, 'xai'); await page.getByText('Speech permissions', { exact: true }).click();
  const input = page.getByRole('checkbox', { name: /^Speech input/ });
  await expect(input).not.toBeChecked(); await input.check(); await save(page);
  expect((await record(page)).allowed_operations).toEqual(['speech_input']);
});
test('read-only operators cannot inspect or manage stored credentials', async ({ page, app }) => {
  await logout(page);
  await login(page, app, 'reader', app.userPassword, location); await ready(page);
  await expect(page.getByRole('button', { name: 'Add external provider', exact: true })).toHaveCount(0);
  const response = await page.request.get(endpoint);
  expect(response.status()).toBe(404);
  expect((await response.json()).error).toBe('NOT_FOUND_OR_FORBIDDEN');
});
