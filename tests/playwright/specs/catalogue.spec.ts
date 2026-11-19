import { test, expect, login, ready, screen, api, type State } from '../fixtures.js';
import type { Page } from '@playwright/test';
const reference = 'catalogue.anthropic.claude-opus-5-5';
const modelRow = (page: Page, id: string) => page.getByRole('row').filter({ hasText: id });
async function model(page: Page, id = reference) { return (await (await page.request.get('/operator/v1/models/' + id)).json()).model; }

test.beforeEach(async ({ page, app }) => { await login(page, app); await ready(page); await screen(page, 'All Models'); });
test('the researched catalogue displays all twelve models without synthetic fixtures', async ({ page }) => {
  await expect(page.locator('.crud-list-table tbody tr')).toHaveCount(12);
  await expect(page.getByRole('checkbox', { name: /^Show test fixtures/ })).not.toBeChecked();
  await expect(modelRow(page, 'cfg.demo')).toHaveCount(0);
});
test('search and fixture visibility are independent', async ({ page }) => {
  await page.getByLabel('Search models, vendors or IDs', { exact: true }).fill('Anthropic');
  await expect(modelRow(page, reference)).toBeVisible();
  await expect(modelRow(page, 'catalogue.openai')).toHaveCount(0);
  await page.getByLabel('Search models, vendors or IDs', { exact: true }).fill('');
  await page.getByRole('checkbox', { name: /^Show test fixtures/ }).check();
  await expect(modelRow(page, 'cfg.demo')).toBeVisible();
});
test('reference prices and source links do not confer runtime authority', async ({ page, app }) => {
  const before = await model(page);
  await modelRow(page, reference).getByRole('button', { name: 'View', exact: true }).click();
  await expect(page.locator('#view-content')).toContainText('Not connected');
  await expect(page.locator('#view-content')).toContainText('USD');
  const links = page.locator('#view-content a[href^="https://"]'); expect(await links.count()).toBeGreaterThan(0);
  expect((await model(page)).catalogue.price_reference).toEqual(before.catalogue.price_reference);
  expect((await app.command<State>('state')).execution_calls).toBe(0);
});
test('editing a display name preserves prices and disconnected state', async ({ page }) => {
  const before = await model(page);
  await modelRow(page, reference).getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('EzLLMRouter display name', { exact: true }).fill('Browser catalogue label');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Browser catalogue label', exact: true })).toBeVisible();
  const after = await model(page); expect(after.display_name).toBe('Browser catalogue label');
  expect(after.catalogue.price_reference).toEqual(before.catalogue.price_reference); expect(after.status).toBe('catalogued');
});
test('archiving requires confirmation and archived records remain inspectable', async ({ page }) => {
  page.once('dialog', dialog => dialog.dismiss()); await modelRow(page, reference).getByRole('button', { name: 'Delete…', exact: true }).click();
  await expect(modelRow(page, reference)).toBeVisible();
  page.once('dialog', dialog => dialog.accept()); await modelRow(page, reference).getByRole('button', { name: 'Delete…', exact: true }).click();
  await expect(modelRow(page, reference)).toHaveCount(0);
  await page.getByRole('checkbox', { name: /^Show archived models/ }).check();
  await expect(modelRow(page, reference)).toContainText('archived');
});
test('an operator can add a disconnected reference with exact prices', async ({ page }) => {
  await page.getByRole('button', { name: 'Add model', exact: true }).click();
  const fields: Record<string, string> = {
    'Unique local key (letters, numbers, dots or hyphens)': 'browser.model', 'Display name': 'Browser reference model',
    Vendor: 'Browser Vendor', Family: 'Browser Family', 'Exact published API model ID': 'browser.reference.v1',
    'Observed version or identifier': 'v1', 'New price snapshot ID': 'browser.price.v1',
    'Reference source title': 'Browser fixture price sheet', 'HTTPS source link': 'https://provider.example/browser-prices',
    'Band 1 uncached input · USD / 1M': '1.25', 'Band 1 output · USD / 1M': '5.50',
  };
  for (const [label, value] of Object.entries(fields)) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(modelRow(page, 'catalogue.operator.browser.model')).toBeVisible();
  const record = await model(page, 'catalogue.operator.browser.model');
  expect(record.status).toBe('catalogued'); expect(record.catalogue.price_reference.bands[0].rates_usd_per_1000000_tokens.output).toBe('5.50');
  expect(record.catalogue.ezllmrouter_registration.execution_approved).toBe(false);
});
test('catalogue records cannot be enabled through a direct registry mutation', async ({ page }) => {
  const record = await model(page);
  const response = await api(page, 'POST', '/operator/v1/registry', { operation_id: 'op.browser.enable-denied',
    action: 'model_state', subject: reference, expected_revision: record.revision, data: { status: 'enabled', reason: 'Browser negative case' } });
  expect(response.status()).toBe(400); expect((await model(page)).status).toBe('catalogued');
});
