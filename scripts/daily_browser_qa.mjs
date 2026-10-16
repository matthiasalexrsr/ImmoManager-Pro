import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const playwright = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(playwright.href);
const { expect } = await import(new URL('./test.mjs', playwright).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let context, api, page;
async function call(method, route, data) {
  const r = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(r.ok(), `${method} ${route}: ${r.status()}`);
  return r.status() === 204 ? null : r.json();
}
async function step(name, run) {
  try { await run(); report.checks.push({ name, ok: true }); }
  catch (error) { report.checks.push({ name, ok: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png') }); throw error; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
try {
  const login = await request.newContext({ baseURL: base.origin });
  const response = await login.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok());
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + (await response.json()).access_token } });
  await login.dispose();
  const user = await call('GET', '/auth/me');
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })); }, user.id);
  page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror', e => report.errors.push(String(e)));
  page.on('request', r => { if (/^https?:/.test(r.url()) && new URL(r.url()).origin !== base.origin) report.external.push(r.url()); });
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(u => u.pathname === '/');
  await step('Settings search, unsaved draft recovery, server persistence and effective density', async () => {
    await page.goto(base.origin + '/settings');
    await expect(page.getByRole('heading', { name: 'Einstellungen finden' })).toBeVisible();
    await page.getByLabel('Suche nach Einstellung oder Bereich').fill('Tabellendichte');
    await page.getByLabel('Tabellendichte', { exact: true }).selectOption('compact');
    await page.reload();
    await page.getByLabel('Suche nach Einstellung oder Bereich').fill('Tabellendichte');
    await expect(page.getByLabel('Tabellendichte', { exact: true })).toHaveValue('compact');
    const card = page.locator('.setting-card').filter({ has: page.getByLabel('Tabellendichte', { exact: true }) });
    await card.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/auth/users/me/preferences')).density).toBe('compact');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
    await page.screenshot({ path: path.join(output, 'settings-1440.png') });
  });
  const task = await call('POST', '/tasks', { title: 'QA Begehung Quelle', status: 'open' });
  const notice = await call('POST', '/notifications', { notification_type: 'task_due', title: 'QA Hinweis öffnen', content: 'Zur richtigen Aufgabe', entity_type: 'task', entity_id: task.id });
  const missing = await call('POST', '/notifications', { notification_type: 'task_due', title: 'QA Quelle fehlt', content: 'Kein falsches Archivieren', entity_type: 'task', entity_id: 'missing-synthetic-task' });
  await step('Notification click loads exact task and archives only the personal receipt', async () => {
    await page.goto(base.origin + '/notifications');
    const inbox = page.getByRole('region', { name: 'Persönliche Benachrichtigungen' });
    await inbox.getByRole('link', { name: 'QA Hinweis öffnen', exact: true }).click();
    await page.waitForURL(u => u.pathname === '/tasks' && u.searchParams.get('notice_id') === notice.id);
    await expect(page.getByText('Hinweis persönlich gelesen und archiviert.', { exact: true })).toBeVisible();
    await expect.poll(async () => (await call('GET', '/notifications/inbox?status=archived')).items.some(n => n.id === notice.id)).toBe(true);
    assert.equal((await call('GET', '/tasks/' + task.id)).status, 'open');
    assert.equal((await call('GET', '/notifications/' + notice.id)).status, 'unread');
    await page.screenshot({ path: path.join(output, 'notification-task-1440.png') });
  });
  await step('Missing source stays unread; archive can reopen a receipt', async () => {
    await page.goto(base.origin + '/notifications');
    const inbox = page.getByRole('region', { name: 'Persönliche Benachrichtigungen' });
    await expect(inbox.getByText('QA Quelle fehlt', { exact: true })).toBeVisible();
    await expect(inbox.getByRole('link', { name: 'QA Quelle fehlt', exact: true })).toHaveCount(0);
    assert.ok((await call('GET', '/notifications/inbox?status=unread')).items.some(n => n.id === missing.id));
    await inbox.getByLabel('Ansicht', { exact: true }).selectOption('archived');
    const row = inbox.locator('li').filter({ has: page.getByRole('link', { name: 'QA Hinweis öffnen', exact: true }) });
    await row.getByRole('button', { name: 'Wieder in den Eingang' }).click();
    await expect.poll(async () => (await call('GET', '/notifications/inbox?status=unread')).items.some(n => n.id === notice.id)).toBe(true);
  });
  await step('Settings responsive at 360px with keyboard focus', async () => {
    await page.setViewportSize({ width: 360, height: 1000 });
    await page.goto(base.origin + '/settings');
    const search = page.getByLabel('Suche nach Einstellung oder Bereich');
    await expect(page.getByLabel('Tabellendichte', { exact: true })).toBeVisible();
    await search.focus(); await expect(search).toBeFocused();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(output, 'settings-360.png') });
  });
  assert.deepEqual(report.errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
