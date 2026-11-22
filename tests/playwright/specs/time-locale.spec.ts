import { test, expect, login, ready } from '../fixtures.js';

const cases = [
  { locale: 'en-US', timezoneId: 'America/Toronto', local: '2030-11-03T03:30', utc: '2030-11-03T08:30:00.000Z',
    gap: '2030-03-10T02:30', fold: '2030-11-03T01:30' },
  { locale: 'de-DE', timezoneId: 'Europe/Berlin', local: '2030-10-27T03:30', utc: '2030-10-27T02:30:00.000Z',
    gap: '2030-03-31T02:30', fold: '2030-10-27T02:30' },
  { locale: 'ar-EG', timezoneId: 'Asia/Kathmandu', local: '2030-01-02T03:30', utc: '2030-01-01T21:45:00.000Z' },
  { locale: 'ja-JP', timezoneId: 'Asia/Tokyo', local: '2030-01-02T03:30', utc: '2030-01-01T18:30:00.000Z' },
  { locale: 'en-AU', timezoneId: 'Australia/Lord_Howe', local: '2030-04-07T03:30', utc: '2030-04-06T17:00:00.000Z',
    gap: '2030-10-06T02:15', fold: '2030-04-07T01:45' },
  { locale: 'en-NZ', timezoneId: 'Pacific/Apia', local: '2011-12-31T03:30', utc: '2011-12-30T13:30:00.000Z',
    gap: '2011-12-30T03:30' },
];
for (const row of cases) {
  test.describe(row.locale + ' / ' + row.timezoneId, () => {
    test.use({ locale: row.locale, timezoneId: row.timezoneId, appOptions: { integrationOnly: true } });
    test('local expiry preserves its instant and rejects gaps and repeated minutes', async ({ page, app }) => {
      await login(page, app); await ready(page);
      const convert = (value: string) => page.evaluate(input => {
        const fn = (window as unknown as { sourceExpiry(value: string): string }).sourceExpiry;
        try { return { utc: fn(input) }; } catch (error) { return { error: String(error) }; }
      }, value);
      expect(await convert(row.local)).toEqual({ utc: row.utc });
      if (row.gap) expect((await convert(row.gap)).error).toContain('daylight-saving gap');
      if (row.fold) expect((await convert(row.fold)).error).toContain('ambiguous');
      expect((await convert('2030-02-30T03:30')).error).toContain('not a valid local time');
    });
    test('UTC date filters and exact costs are independent of browser locale and DST', async ({ page, app }) => {
      await login(page, app, 'admin', app.adminPassword, '/integration#/accounting?source=external&dataset_id=dataset.synthetic.v2');
      await ready(page);
      await expect(page.locator('.card').filter({ hasText: 'Known USD' })).toContainText('0.020000000');
      await page.getByText(/^Report filters · UTC ·/).click();
      await page.getByLabel('From date · inclusive UTC', { exact: true }).fill('2026-11-01');
      await page.getByLabel('Through date · inclusive UTC', { exact: true }).fill('2026-11-01');
      const reply = page.waitForResponse(response => new URL(response.url()).pathname === '/operator/v1/integration/report');
      await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
      const params = new URL((await reply).url()).searchParams;
      expect(params.get('from')).toBe('2026-11-01T00:00:00Z');
      expect(params.get('to')).toBe('2026-11-02T00:00:00Z');
      await ready(page);
      await expect(page.locator('#view-content')).toContainText('No recorded attempts match this collection and filter');
      await page.getByRole('button', { name: 'Clear all filters', exact: true }).click();
      await expect(page.locator('.card').filter({ hasText: 'Known USD' })).toContainText('0.020000000');
      await expect(page.locator('.card').filter({ hasText: 'Unknown cost' })).toContainText('1');
    });
  });
}
