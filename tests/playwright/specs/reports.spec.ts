import { test, expect, login, logout, ready, screen, type State } from '../fixtures.js';
import type { Download } from '@playwright/test';
async function contents(download: Download) {
  const stream = await download.createReadStream(); if (!stream) throw new Error('Download stream unavailable');
  const chunks: Buffer[] = []; for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString('utf8');
}

test('activity filters distinguish completed work from before-send failures', async ({ page, app }) => {
  await login(page, app); await ready(page); await screen(page, 'Activity');
  await expect(page.locator('#view-content tbody tr')).toHaveCount(3);
  await page.getByRole('combobox', { name: 'State', exact: true }).selectOption('failed_before_transmit');
  await expect(page.locator('#view-content tbody tr')).toHaveCount(1);
  await expect(page.locator('#view-content')).toContainText('submission.browser.2');
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
});
test('activity details show the exact attempt and work identity', async ({ page, app }) => {
  await login(page, app); await ready(page); await screen(page, 'Activity');
  await page.getByRole('row').filter({ hasText: 'submission.browser.1' }).getByRole('button').click();
  await expect(page.locator('#view-content')).toContainText('attempt.browser.1');
  await expect(page.locator('#view-content')).toContainText('task.browser.1');
});
test('native usage reports preserve unknown costs rather than displaying zero', async ({ page, app }) => {
  await login(page, app); await ready(page); await screen(page, 'Usage & Costs');
  await expect(page.locator('#view-content')).toContainText('Unknown-cost attempts');
  const report = await (await page.request.get('/operator/v1/usage-costs')).json();
  expect(report.total.attempts).toBe(3); expect(report.total.unknown_cost_attempts).toBe(2);
  expect(report.total.no_provider_charge_attempts).toBe(1);
  expect(report.total.known_subtotals).toEqual({});
});
for (const tab of ['Providers', 'Models', 'Agents', 'People & teams', 'Tasks & workflows', 'Technical diagnostics']) {
  test('native Usage & Costs opens its ' + tab + ' section', async ({ page, app }) => {
    await login(page, app); await ready(page); await screen(page, 'Usage & Costs');
    await page.locator('#view-content').getByRole('button', { name: tab, exact: true }).click();
    await expect(page.locator('#view-content')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toHaveCount(0);
    expect((await app.command<State>('state')).submissions).toBe(3);
  });
}
for (const format of ['CSV', 'JSON']) {
  test('native report exports the current attempt page as ' + format, async ({ page, app }) => {
    await login(page, app); await ready(page); await screen(page, 'Usage & Costs');
    const button = page.getByRole('button', { name: 'Export attempt page · ' + format, exact: true });
    await expect(button).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), button.click()]);
    expect(download.suggestedFilename()).toBe('ezllmrouter-usage-costs.' + format.toLowerCase());
    const raw = await contents(download);
    const ids = ['attempt.browser.1', 'attempt.browser.2', 'attempt.browser.3'];
    if (format === 'JSON') {
      const report = JSON.parse(raw);
      expect(report.total.attempts).toBe(3);
      expect(report.attempt_pagination).toMatchObject({ page: 1, limit: 100, total: 3 });
      expect(report.attempts.map((item: { attempt_id: string }) => item.attempt_id).sort()).toEqual(ids);
    } else {
      const rows = raw.trim().split(/\r?\n/);
      expect(rows).toHaveLength(4);
      const column = rows[0].split(',').indexOf('attempt_id');
      expect(column).toBeGreaterThanOrEqual(0);
      expect(rows.slice(1).map(row => row.split(',')[column]).sort()).toEqual(ids);
    }
  });
}

test.describe('external accounting', () => {
  test.use({ appOptions: { integrationOnly: true } });
  test.beforeEach(async ({ page, app }) => {
    await login(page, app, 'admin', app.adminPassword, '/integration#/accounting?source=external&dataset_id=dataset.synthetic.v2'); await ready(page);
  });
  test('known revision replaces the earlier unknown charge exactly once', async ({ page }) => {
    const card = page.locator('.card').filter({ hasText: 'Known USD' });
    await expect(card).toContainText('0.020000000');
    await expect(page.locator('.card').filter({ hasText: 'Unknown cost' })).toContainText('1');
    const report = await (await page.request.get('/operator/v1/integration/report?dataset_id=dataset.synthetic.v2')).json();
    expect(report.attempt_count).toBe(2); expect(report.known_total_by_currency.USD).toBe('0.020000000');
  });
  test('a late usage correction updates the subtotal without adding an attempt', async ({ page, app }) => {
    await app.command('correct_usage'); await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.locator('.card').filter({ hasText: 'Known USD' })).toContainText('0.030000000');
    const report = await (await page.request.get('/operator/v1/integration/report?dataset_id=dataset.synthetic.v2')).json();
    expect(report.attempt_count).toBe(2); expect(report.known_total_by_currency.USD).toBe('0.030000000');
  });
  for (const tab of ['Overview', 'Providers', 'Models', 'Agents', 'People & teams', 'Tasks & workflows']) {
    test('external accounting renders ' + tab + ' with its route preserved', async ({ page }) => {
      await page.getByRole('navigation', { name: 'Accounting sections', exact: true }).getByRole('button', { name: tab, exact: true }).click();
      await expect(page.locator('#view-title')).toHaveText('Accounting · ' + tab);
      await ready(page); await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toHaveCount(0);
      await page.reload(); await ready(page); await expect(page.locator('#view-title')).toHaveText('Accounting · ' + tab);
    });
  }
  test('filters produce an honest empty state and can be cleared', async ({ page }) => {
    await page.getByText(/^Report filters · UTC ·/).click();
    await page.getByLabel('Task', { exact: true }).fill('task.absent');
    await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
    await expect(page.locator('#view-content')).toContainText('No recorded attempts match this collection and filter');
    await page.getByRole('button', { name: 'Clear all filters', exact: true }).click();
    await expect(page.locator('.card').filter({ hasText: 'Known USD' })).toContainText('0.020000000');
  });
  for (const format of ['CSV', 'JSON']) {
    test('external accounting exports the exact ' + format + ' report', async ({ page }) => {
      await page.getByText('Exact filtered report exports', { exact: true }).click();
      const downloading = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export ' + format, exact: true }).click();
      const download = await downloading; expect(download.suggestedFilename()).toBe('ezllmrouter-integration-report.' + format.toLowerCase());
      const raw = await contents(download);
      if (format === 'JSON') { const report = JSON.parse(raw); expect(report.attempt_count).toBe(2); expect(report.known_total_by_currency.USD).toBe('0.020000000'); }
      else { expect(raw).toContain('attempt_id'); expect(raw).toContain('attempt.synthetic'); expect(raw).toContain('0.020000000'); }
    });
  }
  test('read-only operators can inspect accounting and export but cannot administer', async ({ page, app }) => {
    await logout(page);
    await login(page, app, 'reader', app.userPassword, '/integration#/accounting?source=external&dataset_id=dataset.synthetic.v2'); await ready(page);
    await expect(page.locator('.card').filter({ hasText: 'Known USD' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button', { name: 'External Providers', exact: true })).toHaveCount(0);
    const response = await page.request.get('/operator/v1/users'); expect(response.status()).toBe(403);
  });
});

test.describe('empty data', () => {
  test.use({ appOptions: { seed: false } });
  test('empty activity and usage do not imply successful work or known zero cost', async ({ page, app }) => {
    await login(page, app); await ready(page); await screen(page, 'Activity');
    await expect(page.locator('#view-content')).toContainText('No submissions match this filter');
    await screen(page, 'Usage & Costs'); await expect(page.getByRole('heading', { name: 'No recorded attempts', exact: true })).toBeVisible();
    expect((await app.command<State>('state')).submissions).toBe(0);
  });
});
test('scripted demo workspaces remain separate from recorded service activity', async ({ page, app }) => {
  await login(page, app); await ready(page); await screen(page, 'Usage & Costs');
  await page.getByRole('button', { name: 'Open demo workspace', exact: true }).click();
  await expect(page.locator('#view-content')).toContainText(/demo/i);
  const state = await app.command<State>('state');
  expect(state).toMatchObject({ submissions: 3, execution_calls: 0, inference_requests: 0 });
});
