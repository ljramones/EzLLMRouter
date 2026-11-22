import AxeBuilder from '@axe-core/playwright';
import { test, expect, login, ready, screen } from '../fixtures.js';
import type { Page } from '@playwright/test';
import { views } from '../console-contracts.js';

async function audit(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  expect(result.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(node => ({ target: node.target, summary: node.failureSummary })) }))).toEqual([]);
}

for (const view of views) {
  test('WCAG audit: ' + view, async ({ page, app }) => {
    await login(page, app); await ready(page); await screen(page, view);
    await audit(page);
  });
}

test('sign-in and invalid credentials remain accessible', async ({ page, app }) => {
  await page.goto('/'); await audit(page);
  await page.getByLabel('Username', { exact: true }).fill('admin');
  await page.getByLabel('Password', { exact: true }).fill('incorrect passphrase');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('#login-error')).not.toBeEmpty(); await audit(page);
});

test('account form at 200 percent zoom and reduced motion supports keyboard cancellation', async ({ page, app }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await login(page, app); await ready(page); await screen(page, 'Users & Permissions');
  await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).zoom)).toBe('2');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.getByLabel(/^Username ·/)).toBeFocused();
  await page.getByLabel('Full name', { exact: true }).fill('Keyboard at 200 percent');
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  await audit(page);
  const dialogs: string[] = [];
  page.on('dialog', async dialog => { dialogs.push(dialog.message()); await dialog.accept(); });
  const cancel = page.getByRole('button', { name: 'Cancel', exact: true });
  await expect(cancel).toHaveAttribute('type', 'button');
  await cancel.focus(); await expect(cancel).toBeFocused();
  await cancel.press('Enter');
  await expect(page.locator('#view-title')).toBeFocused();
  expect(dialogs).toEqual(['Discard unsaved changes?']);
});

test.describe('required password change', () => {
  test.use({ appOptions: { bootstrap: true } });
  test('password change form has accessible labels and errors', async ({ page, app }) => {
    await login(page, app, 'admin', app.bootstrapPassword);
    await expect(page.locator('#password-view')).toBeVisible(); await audit(page);
  });
});

for (const username of ['reader', 'member']) {
  test('role navigation is accessible: ' + username, async ({ page, app }) => {
    await login(page, app, username, app.userPassword); await ready(page); await audit(page);
  });
}

test('API retry state is accessible', async ({ page, app }) => {
  await login(page, app); await ready(page);
  await page.route('**/operator/v1/models', route => route.fulfill({ status: 503,
    contentType: 'application/json', body: '{"error":"METADATA_UNAVAILABLE"}' }));
  await screen(page, 'All Models');
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible(); await audit(page);
});

test.describe('external accounting sections', () => {
  test.use({ appOptions: { integrationOnly: true } });
  for (const section of ['Overview', 'Providers', 'Models', 'Agents', 'People & teams', 'Tasks & workflows']) {
    test('WCAG audit: accounting ' + section, async ({ page, app }) => {
      await login(page, app, 'admin', app.adminPassword, '/integration#/accounting?source=external&dataset_id=dataset.synthetic.v2');
      await ready(page);
      await page.getByRole('navigation', { name: 'Accounting sections', exact: true }).getByRole('button', { name: section, exact: true }).click();
      await ready(page); await audit(page);
    });
  }
});

test('accessibility checker detects an unlabeled control', async ({ page, app }) => {
  await login(page, app); await ready(page);
  await page.locator('#view-content').evaluate(element => element.appendChild(document.createElement('input')));
  const result = await new AxeBuilder({ page }).withTags(['wcag2a']).analyze();
  expect(result.violations.map(violation => violation.id)).toContain('label');
});
