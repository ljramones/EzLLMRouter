import { test as base, expect, type Page, type APIResponse, type BrowserContext } from '@playwright/test';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { existsSync } from 'node:fs';

export { expect };
export type AppOptions = { bootstrap?: boolean; seed?: boolean; integrationOnly?: boolean };
export type State = { submissions: number; datasets: number; execution_calls: number; inference_requests: number; metadata_requests: string[]; credential_metadata_probes: number };
type Ready = { origin: string; inventoryOrigin: string; users: Record<string, string>; adminPassword: string; bootstrapPassword: string; userPassword: string };
export type App = Ready & { command<T = Record<string, unknown>>(command: string, values?: Record<string, unknown>): Promise<T> };
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

export async function guardContext(context: BrowserContext, origin: string) {
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin || ['about:', 'data:', 'blob:'].includes(url.protocol)) return route.continue();
    return route.abort('blockedbyclient');
  });
}

export const test = base.extend<{ appOptions: AppOptions; app: App; browserErrors: void }>({
  appOptions: [{}, { option: true }],
  app: async ({ appOptions }, use, testInfo) => {
    const python = process.env.EZLLMROUTER_TEST_PYTHON || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    if (!existsSync(python)) throw new Error('Install the locked Python environment, or set EZLLMROUTER_TEST_PYTHON to its Python executable.');
    const child = spawn(python, ['-B', path.join(repo, 'tests/playwright/server.py'), '--options', JSON.stringify(appOptions)], {
      cwd: repo, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    let stderr = '', next = 0;
    child.stderr.on('data', data => { stderr = (stderr + data.toString()).slice(-100_000); });
    const pending = new Map<number, { resolve(value: unknown): void; reject(error: Error): void; timer: ReturnType<typeof setTimeout> }>();
    let readyResolve!: (value: Ready) => void, readyReject!: (error: Error) => void;
    const ready = new Promise<Ready>((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
    const startupTimer = setTimeout(() => readyReject(new Error('Console startup timed out: ' + stderr)), 20_000);
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      try {
        const message = JSON.parse(line);
        if (message.ready) { clearTimeout(startupTimer); readyResolve(message); return; }
        const waiting = pending.get(message.id);
        if (!waiting) return;
        pending.delete(message.id); clearTimeout(waiting.timer);
        if (message.error) waiting.reject(new Error(message.error)); else waiting.resolve(message.value);
      } catch (error) { readyReject(new Error('Invalid fixture response: ' + String(error))); }
    });
    const exited = new Promise<number | null>(resolve => child.once('close', (code) => {
      clearTimeout(startupTimer);
      const error = new Error('Console fixture exited (' + code + '): ' + stderr);
      readyReject(error);
      for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
      pending.clear(); resolve(code);
    }));
    child.once('error', error => { clearTimeout(startupTimer); readyReject(error); });
    const command: App['command'] = (name, values = {}) => new Promise((resolve, reject) => {
      const id = ++next;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('Fixture command timed out: ' + name + '\n' + stderr)); }, 15_000);
      pending.set(id, { resolve: value => resolve(value as never), reject, timer });
      child.stdin.write(JSON.stringify({ id, command: name, ...values }) + '\n');
    });
    let started = false;
    try {
      const info = await ready; started = true;
      await use({ ...info, command });
      const state = await command<State>('state');
      expect(state.execution_calls, 'Browser tests must not invoke an execution runner').toBe(0);
      expect(state.inference_requests, 'Inventory fixtures must never receive inference requests').toBe(0);
    } finally {
      clearTimeout(startupTimer);
      if (child.exitCode === null && started) await command('stop').catch(() => undefined);
      child.stdin.end();
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
      const code = await exited; clearTimeout(timer); lines.close();
      if (testInfo.status !== testInfo.expectedStatus) await testInfo.attach('console.log', { body: stderr, contentType: 'text/plain' });
      if (started) expect(code, 'Console shutdown must release its jobs, sockets and database').toBe(0);
    }
  },
  baseURL: async ({ app }, use) => { await use(app.origin); },
  browserErrors: [async ({ context, app }, use) => {
    const errors: string[] = [];
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    await guardContext(context, app.origin);
    await use();
    expect(errors, 'No uncaught JavaScript errors').toEqual([]);
  }, { auto: true }],
});

export async function login(page: Page, app: App, username = 'admin', password = app.adminPassword, location = '/') {
  await page.goto(location);
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}
export async function logout(page: Page) {
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.locator('#login-view')).toBeVisible();
}
export async function restartAndLogin(page: Page, app: App, location = '/') {
  // Hash-only navigation can leave the old authenticated document in place.
  await page.goto('about:blank');
  await app.command('restart');
  expect((await page.request.get('/operator/v1/session')).status()).toBe(401);
  await login(page, app, 'admin', app.adminPassword, location);
  await ready(page);
}
export async function ready(page: Page) {
  await expect(page.locator('#workspace')).toBeVisible();
  await expect(page.locator('#view-content')).toHaveAttribute('aria-busy', 'false');
}
export async function screen(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Primary', exact: true }).getByRole('button', { name, exact: true }).click();
  await ready(page);
}
export async function changePassword(page: Page, current: string, replacement: string) {
  await page.getByLabel('Current password', { exact: true }).fill(current);
  await page.getByLabel('New password', { exact: true }).fill(replacement);
  await page.getByLabel('Confirm new password', { exact: true }).fill(replacement);
  await page.getByRole('button', { name: 'Update password', exact: true }).click();
  await expect(page.locator('#login-view')).toBeVisible();
}
export async function api(page: Page, method: string, url: string, data?: unknown, extra: Record<string, string> = {}): Promise<APIResponse> {
  const response = await page.request.get('/operator/v1/session');
  const session = response.ok() ? await response.json() : {};
  return page.request.fetch(url, { method, data,
    headers: { Origin: new URL(page.url()).origin, 'X-EzLLMRouter-CSRF': session.csrf || '', ...extra } });
}
export async function users(page: Page) {
  const response = await page.request.get('/operator/v1/users');
  expect(response.ok()).toBeTruthy();
  return (await response.json()).items as Array<Record<string, any>>;
}
export async function createUser(page: Page, username: string, role = 'ordinary') {
  await screen(page, 'Users & Permissions');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await page.getByLabel(/^Username ·/).fill(username);
  await page.getByLabel('Full name', { exact: true }).fill('Browser ' + username);
  await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption(role);
  await page.getByLabel(/^Temporary password ·/).fill('New browser temporary passphrase!');
  await page.getByLabel('Confirm temporary password', { exact: true }).fill('New browser temporary passphrase!');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'User accounts', exact: true })).toBeVisible();
  return (await users(page)).find(user => user.username === username)!;
}
