import { test, expect, login, ready, screen } from '../fixtures.js';
import { contracts, validate, views } from '../console-contracts.js';

test('every main screen consumes real payloads matching its field contracts', async ({ page, app }) => {
  const responses = new Set<string>();
  const errors: string[] = [];
  const pending: Promise<void>[] = [];
  page.on('response', response => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/operator/v1/') || /session|login|logout/.test(url.pathname)) return;
    pending.push(response.json().then(value => {
      expect(response.ok(), url.pathname).toBe(true);
      expect(contracts[url.pathname], 'Unreviewed console payload: ' + url.pathname).toBeDefined();
      validate(value, contracts[url.pathname]); responses.add(url.pathname);
      // Every required top-level field is independently removed and mistyped.
      for (const key of Object.keys(contracts[url.pathname])) {
        const missing = { ...value }; delete missing[key];
        expect(() => validate(missing, contracts[url.pathname])).toThrow(/missing/);
        expect(() => validate({ ...value, [key]: null }, contracts[url.pathname])).toThrow(/mismatch/);
      }
    }).catch(error => { errors.push(url.pathname + ': ' + String(error)); }));
  });
  await login(page, app); await ready(page);
  expect((await page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button').allTextContents()).sort()).toEqual([...views].sort());
  for (const view of views) {
    await screen(page, view);
    await expect(page.locator('#view-title')).toHaveText(view); await ready(page);
    await expect(page.getByRole('heading', { name: 'Unable to load current data', exact: true })).toHaveCount(0);
    await expect(page.locator('#view-title')).not.toBeEmpty();
  }
  await expect.poll(() => responses.size).toBe(Object.keys(contracts).length);
  await Promise.all(pending);
  expect(errors).toEqual([]);
  expect([...responses].sort()).toEqual(Object.keys(contracts).sort());
});

test('consumer contracts reject nested field loss and decimal coercion', () => {
  expect(() => validate({ attempts: [{ attempt_id: 'synthetic' }] }, { attempts: [{ attempt_id: 'string', amount_decimal: 'decimal|null' }] })).toThrow(/amount_decimal/);
  for (const value of [0.02, '', 'NaN', '1e-3', '0,02', '٠.٠٢']) {
    expect(() => validate({ USD: value }, 'decimal-map')).toThrow(/mismatch/);
  }
  validate({ USD: '0.020000000' }, 'decimal-map');
  expect(() => validate({}, 'unreviewed-type')).toThrow(/Unknown/);
});
