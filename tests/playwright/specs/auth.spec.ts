import { test, expect, login, ready, changePassword, api } from '../fixtures.js';

test('sign-in fields are labelled, required and focused', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Username', { exact: true })).toHaveAttribute('required', '');
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('type', 'password');
  await expect(page.locator('#workspace')).toBeHidden();
});
test('invalid credentials show an error and clear the password', async ({ page, app }) => {
  await login(page, app, 'admin', 'wrong browser passphrase');
  await expect(page.locator('#login-error')).toBeVisible();
  await expect(page.getByLabel('Password', { exact: true })).toBeEmpty();
  await expect(page.locator('#workspace')).toBeHidden();
});
test('a named session survives reload', async ({ page, app }) => {
  await login(page, app); await ready(page); await page.reload(); await ready(page);
  await expect(page.locator('#account-button')).toContainText('admin');
  const response = await page.request.get('/operator/v1/session');
  expect((await response.json()).username).toBe('admin');
});
test('session cookies are HttpOnly, scoped and SameSite', async ({ page, context, app }) => {
  await login(page, app); await ready(page);
  const cookie = (await context.cookies()).find(value => value.name === 'ezllmrouter_operator');
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/operator' });
  expect(await page.evaluate(() => document.cookie)).not.toContain('ezllmrouter_operator');
});
test('sign-out invalidates the server session and clears passwords', async ({ page, app }) => {
  await login(page, app); await ready(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.locator('#login-view')).toBeVisible();
  expect((await page.request.get('/operator/v1/session')).status()).toBe(401);
  await page.reload(); await expect(page.locator('#workspace')).toBeHidden();
  await expect(page.getByLabel('Password', { exact: true })).toBeEmpty();
});
test('expired sessions return to sign-in on the next request', async ({ page, app }) => {
  await login(page, app); await ready(page); await app.command('expire_sessions');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.locator('#login-view')).toBeVisible();
  await expect(page.locator('#login-error')).toContainText('expired');
});
test('optional password change can be cancelled with focus restored', async ({ page, app }) => {
  await login(page, app); await ready(page); await page.locator('#account-button').click();
  await expect(page.getByLabel('Current password', { exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('#workspace')).toBeVisible();
  await expect(page.locator('#account-button')).toBeFocused();
});
test('a rejected password change clears secret inputs and keeps the session', async ({ page, app }) => {
  await login(page, app); await ready(page); await page.locator('#account-button').click();
  await changePasswordAttempt(page, 'wrong current passphrase', 'Browser replacement passphrase!');
  await expect(page.locator('#password-error')).toBeVisible();
  for (const id of ['current-password', 'new-password', 'confirm-password']) await expect(page.locator('#' + id)).toBeEmpty();
  expect((await page.request.get('/operator/v1/session')).status()).toBe(200);
});
async function changePasswordAttempt(page: import('@playwright/test').Page, current: string, password: string) {
  await page.getByLabel('Current password', { exact: true }).fill(current);
  await page.getByLabel('New password', { exact: true }).fill(password);
  await page.getByLabel('Confirm new password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Update password', exact: true }).click();
}

test.describe('first sign-in', () => {
  test.use({ appOptions: { bootstrap: true } });
  test('temporary passwords require a change before navigation or API access', async ({ page, app }) => {
    await login(page, app, 'admin', app.bootstrapPassword);
    await expect(page.getByRole('heading', { name: 'Change your password', exact: true })).toBeVisible();
    await expect(page.locator('#workspace')).toBeHidden();
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeHidden();
    expect((await page.request.get('/operator/v1/users')).status()).toBe(403);
    expect((await api(page, 'POST', '/operator/v1/users', {})).status()).toBe(403);
  });
  test('password confirmation mismatches stay on the change screen', async ({ page, app }) => {
    await login(page, app, 'admin', app.bootstrapPassword);
    await page.getByLabel('Current password', { exact: true }).fill(app.bootstrapPassword);
    await page.getByLabel('New password', { exact: true }).fill('Browser new password one!');
    await page.getByLabel('Confirm new password', { exact: true }).fill('Browser new password two!');
    await page.getByRole('button', { name: 'Update password', exact: true }).click();
    await expect(page.locator('#password-error')).toHaveText('Passwords do not match.');
  });
  test('changing the bootstrap password requires a fresh sign-in', async ({ page, app }) => {
    await login(page, app, 'admin', app.bootstrapPassword);
    await changePassword(page, app.bootstrapPassword, app.adminPassword);
    expect((await page.request.get('/operator/v1/session')).status()).toBe(401);
    await login(page, app); await ready(page);
    expect((await (await page.request.get('/operator/v1/session')).json()).must_change_password).toBe(false);
  });
  test('Unicode and surrounding spaces are preserved exactly', async ({ page, app }) => {
    const password = '  Pāss phrase 🔐 browser 2026  ';
    await login(page, app, 'admin', app.bootstrapPassword);
    await changePassword(page, app.bootstrapPassword, password);
    await login(page, app, 'admin', password.trim());
    await expect(page.locator('#login-error')).toBeVisible();
    await login(page, app, 'admin', password); await ready(page);
  });
});
