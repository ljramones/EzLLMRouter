import { test, expect, login, logout, ready, restartAndLogin, screen, api, users, createUser, guardContext } from '../fixtures.js';
const rowFor = (page: import('@playwright/test').Page, username: string) => page.getByRole('row').filter({ has: page.getByRole('cell', { name: username, exact: true }) });

test.beforeEach(async ({ page, app }) => { await login(page, app); await ready(page); await screen(page, 'Users & Permissions'); });
test('accounts display roles and permissions and can be searched', async ({ page }) => {
  await expect(rowFor(page, 'reader')).toContainText('Read-only');
  await page.getByLabel('Search users', { exact: true }).fill('reader');
  await expect(rowFor(page, 'reader')).toBeVisible(); await expect(rowFor(page, 'member')).toHaveCount(0);
});
test('creating a user persists the account without granting model use', async ({ page }) => {
  const record = await createUser(page, 'new.browser');
  expect(record).toMatchObject({ username: 'new.browser', role: 'ordinary', status: 'active', must_change_password: true });
  const response = await page.request.get('/operator/v1/principals/' + record.principal_id);
  expect((await response.json()).grants).toEqual([]);
  await page.reload(); await ready(page); await expect(rowFor(page, 'new.browser')).toBeVisible();
});
test('a duplicate username is rejected without creating another account', async ({ page }) => {
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await page.getByLabel(/^Username ·/).fill('reader'); await page.getByLabel('Full name', { exact: true }).fill('Duplicate');
  await page.getByLabel(/^Temporary password ·/).fill('Browser duplicate passphrase!');
  await page.getByLabel('Confirm temporary password', { exact: true }).fill('Browser duplicate passphrase!');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.locator('#view-content [role=alert]')).toContainText('Change rejected');
  expect((await users(page)).filter(user => user.username === 'reader')).toHaveLength(1);
});
test('temporary password confirmation is checked before account creation', async ({ page }) => {
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await page.getByLabel(/^Username ·/).fill('mismatch'); await page.getByLabel('Full name', { exact: true }).fill('Mismatch');
  await page.getByLabel(/^Temporary password ·/).fill('Browser first passphrase!');
  await page.getByLabel('Confirm temporary password', { exact: true }).fill('Browser other passphrase!');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.locator('#view-content [role=alert]')).toContainText('Passwords do not match');
  expect((await users(page)).some(user => user.username === 'mismatch')).toBe(false);
});
test('editing a user persists the new display name and role', async ({ page }) => {
  await rowFor(page, 'reader').getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Full name', { exact: true }).fill('Updated reader');
  await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption('ordinary');
  await page.getByRole('button', { name: 'Save user', exact: true }).click();
  await expect(rowFor(page, 'reader')).toContainText('Updated reader');
  expect((await users(page)).find(user => user.username === 'reader')?.role).toBe('ordinary');
});
test('disabled users cannot start a new session', async ({ page, app }) => {
  await rowFor(page, 'member').getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByRole('combobox', { name: 'Account status', exact: true }).selectOption('suspended');
  await page.getByRole('button', { name: 'Save user', exact: true }).click();
  await expect(rowFor(page, 'member')).toContainText('Disabled');
  await logout(page);
  await login(page, app, 'member', app.userPassword); await expect(page.locator('#login-error')).toBeVisible();
});
test('deletion requires confirmation and revokes access', async ({ page }) => {
  page.once('dialog', dialog => dialog.dismiss());
  await rowFor(page, 'member').getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(rowFor(page, 'member')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await rowFor(page, 'member').getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(rowFor(page, 'member')).toHaveCount(0);
  expect((await users(page)).some(user => user.username === 'member')).toBe(false);
});
test('the last administrator is protected in both UI and API', async ({ page }) => {
  await expect(rowFor(page, 'admin').getByRole('button', { name: 'Delete', exact: true })).toBeDisabled();
  const admin = (await users(page)).find(user => user.username === 'admin')!;
  const response = await api(page, 'DELETE', '/operator/v1/users/' + admin.principal_id, { expected_revision: admin.revision });
  expect(response.status()).toBe(409);
  expect((await response.json()).error).toBe('LAST_ACTIVE_ADMIN');
  expect((await users(page)).find(user => user.username === 'admin')?.status).toBe('active');
});
test('stale edits preserve newer server data', async ({ page }) => {
  const reader = (await users(page)).find(user => user.username === 'reader')!;
  await rowFor(page, 'reader').getByRole('button', { name: 'Edit', exact: true }).click();
  const data = { username: reader.username, display_name: 'Concurrent update', role: reader.role, status: reader.status, expected_revision: reader.revision };
  expect((await api(page, 'POST', '/operator/v1/users/' + reader.principal_id, data)).ok()).toBeTruthy();
  await page.getByLabel('Full name', { exact: true }).fill('Stale overwrite');
  await page.getByRole('button', { name: 'Save user', exact: true }).click();
  await expect(page.locator('#view-content [role=alert]')).toContainText('USER_CONFLICT');
  expect((await users(page)).find(user => user.username === 'reader')?.display_name).toBe('Concurrent update');
});
test('unsaved edits can keep the form or be discarded on navigation', async ({ page }) => {
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await page.getByLabel('Full name', { exact: true }).fill('Unsaved person');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button', { name: 'Build & context', exact: true }).click();
  await expect(page.getByLabel('Full name', { exact: true })).toHaveValue('Unsaved person');
  page.once('dialog', dialog => dialog.accept()); await screen(page, 'Build & context');
  await expect(page.locator('#view-title')).toHaveText('Build & context');
});
test('a password reset signs out another browser context and requires a new password', async ({ page, app, browser }) => {
  const other = await browser.newContext({ baseURL: app.origin }); await guardContext(other, app.origin);
  try {
    const member = await other.newPage(); await login(member, app, 'member', app.userPassword); await ready(member);
    await rowFor(page, 'member').getByRole('button', { name: 'Reset password', exact: true }).click();
    await page.getByLabel(/^Temporary password ·/).fill('Reset browser temporary passphrase!');
    await page.getByLabel('Confirm temporary password', { exact: true }).fill('Reset browser temporary passphrase!');
    await page.getByRole('button', { name: 'Reset password', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'User accounts', exact: true })).toBeVisible();
    await member.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(member.locator('#login-view')).toBeVisible();
    await login(member, app, 'member', 'Reset browser temporary passphrase!');
    await expect(member.locator('#password-view')).toBeVisible();
  } finally { await other.close(); }
});
test('saved users survive a complete service restart', async ({ page, app }) => {
  await createUser(page, 'restart.browser');
  await restartAndLogin(page, app); await screen(page, 'Users & Permissions');
  await expect(rowFor(page, 'restart.browser')).toBeVisible();
});
test('model access is granted and removed explicitly without model execution', async ({ page, app }) => {
  const memberId = app.users.member;
  await rowFor(page, 'member').getByRole('button', { name: 'Model access', exact: true }).click();
  await page.getByRole('combobox', { name: 'Source-permitted configuration', exact: true }).selectOption('cfg.demo');
  await page.getByRole('button', { name: 'Save grant', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/operator/v1/principals/' + memberId)).json()).grants.find((g: any) => g.configuration_ref === 'cfg.demo')?.status).toBe('active');
  await screen(page, 'Users & Permissions');
  await rowFor(page, 'member').getByRole('button', { name: 'Model access', exact: true }).click();
  await page.getByRole('combobox', { name: 'Source-permitted configuration', exact: true }).selectOption('cfg.demo');
  await page.getByRole('combobox', { name: 'Access state', exact: true }).selectOption('removed');
  await page.getByRole('button', { name: 'Save grant', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/operator/v1/principals/' + memberId)).json()).grants.find((g: any) => g.configuration_ref === 'cfg.demo')?.status).toBe('removed');
  expect((await app.command<{ execution_calls: number }>('state')).execution_calls).toBe(0);
});
test('changing an active user role invalidates their earlier browser session', async ({ page, app, browser }) => {
  const context = await browser.newContext({ baseURL: app.origin }); await guardContext(context, app.origin);
  try {
    const member = await context.newPage(); await login(member, app, 'member', app.userPassword); await ready(member);
    await rowFor(page, 'member').getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption('read_only_operator');
    await page.getByRole('button', { name: 'Save user', exact: true }).click();
    await expect(rowFor(page, 'member')).toContainText('Read-only');
    await member.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(member.locator('#login-view')).toBeVisible();
    await login(member, app, 'member', app.userPassword); await ready(member);
    expect((await member.request.get('/operator/v1/users')).status()).toBe(403);
  } finally { await context.close(); }
});
