// Real browser checks, with only the local contract-wizard preview provider.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || ['8000', '8765'].includes(base.port)
    || base.pathname !== '/' || base.username || process.env.QA_ALLOW_TEST_WRITES !== '1'
    || !process.env.QA_PASSWORD || !process.env.QA_PLAYWRIGHT_PATH || !process.env.QA_READER_ID) {
  throw new Error('This browser gate requires a disposable owned synthetic loopback server.');
}
const { chromium, request, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
const out = path.resolve(process.env.QA_OUTPUT);
await fs.mkdir(out, { recursive: true });
const report = { syntheticOnly: true, checks: [], errors: [], screenshots: [] };
const browser = await chromium.launch({ channel: 'chromium', headless: true });
report.browserVersion = browser.version();
let context, page, api;
const step = async (name, action) => {
  try { await action(); report.checks.push({ name, ok: true }); console.log('PASS ' + name); }
  catch (failure) {
    report.checks.push({ name, ok: false, error: String(failure) });
    await page?.screenshot({ path: path.join(out, 'failure-' + report.checks.length + '.png'),
      fullPage: true }).catch(() => {});
    throw failure;
  } finally { await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(report, null, 2)); }
};
const apiCall = async (method, url, data) => {
  const response = await api.fetch('/api/v1' + url, { method, data });
  assert.ok(response.ok(), method + ' ' + url + ' got HTTP ' + response.status());
  return response.status() === 204 ? null : response.json();
};
async function login(target, name='owner') {
  await target.goto(base.origin + '/login');
  await target.locator('input[autocomplete="username"]').fill(name);
  await target.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await target.locator('form button[type="submit"]').click();
  await target.waitForURL(url => url.pathname === '/');
  const later = target.getByRole('button', { name: 'Später', exact: true });
  if (await later.isVisible().catch(() => false)) await later.click();
}
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const loginResponse = await setup.post('/api/v1/auth/login', {
    data: { username: 'owner', password: process.env.QA_PASSWORD },
  });
  assert.ok(loginResponse.ok());
  const tokens = await loginResponse.json();
  await setup.dispose();
  api = await request.newContext({ baseURL: base.origin,
    extraHTTPHeaders: { Authorization: 'Bearer ' + tokens.access_token } });
  const profile = await apiCall('GET', '/auth/me');
  context = await browser.newContext({ viewport: { width: 1440, height: 950 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, profile.id);
  page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => report.errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /(?:Content.Security.Policy|ErrorBoundary caught:)/i.test(message.text())) report.errors.push(`UI console: ${message.text()}`); });
  let connectionId, runId;
  await step('Actual login and provider selection without external action', async () => {
    await login(page);
    await page.goto(base.origin + '/integration-connections');
    await expect(page.getByRole('heading', { name: 'Verbindungen und Vorgänge' })).toBeVisible();
    await page.getByRole('button', { name: 'Verbindung anlegen', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Verbindung anlegen' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Anbieter').selectOption('contract-wizard');
    await dialog.getByLabel('Bezeichnung *').fill('QA Lokalvertrag');
    await dialog.getByLabel('Verbindung aktivieren').check();
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'QA Lokalvertrag' })).toBeVisible();
    const list = await apiCall('GET', '/integration-connections?limit=20');
    assert.equal(list.total, 1);
    assert.equal(list.items[0].provider_id, 'contract-wizard');
    connectionId = list.items[0].id;
    const runs = await apiCall('GET', '/integration-connections/' + connectionId + '/runs');
    assert.equal(runs.total, 0);
  });
  await step('Frozen preview exists before any provider execution', async () => {
    const form = page.locator('.connection-action-form');
    await expect(form).toBeVisible();
    await form.getByLabel('Mietername').fill('Synthetische Anna');
    await form.getByLabel('Objekt').fill('Synthetisches Haus');
    await form.getByRole('button', { name: 'Vorschau erstellen' }).click();
    await expect(page.getByRole('heading', { name: 'Vorgang: Vorbereitet' })).toBeVisible();
    const list = await apiCall('GET', '/integration-connections/' + connectionId + '/runs');
    assert.equal(list.total, 1);
    runId = list.items[0].id;
    assert.equal(list.items[0].attempts, 0);
    const frozen = await apiCall('GET', '/integration-connections/' + connectionId + '/runs/' + runId + '/preview');
    assert.equal(frozen.payload.tenant_name, 'Synthetische Anna');
    assert.equal(frozen.external_action_started, false);
    await expect(page.getByRole('button', { name: 'Jetzt ausführen' })).toBeDisabled();
  });
  await step('Independent confirmation creates exactly one saved provider result', async () => {
    await page.getByLabel('Diesen vorbereiteten Schritt jetzt ausführen.').check();
    await page.getByRole('button', { name: 'Jetzt ausführen' }).click();
    await expect(page.getByRole('heading', { name: 'Vorgang: Abgeschlossen' })).toBeVisible();
    const list = await apiCall('GET', '/integration-connections/' + connectionId + '/runs');
    assert.equal(list.total, 1);
    assert.equal(list.items[0].id, runId);
    assert.equal(list.items[0].attempts, 1);
    assert.ok(list.items[0].result_bytes > 0);
    await expect(page.getByRole('button', { name: 'Jetzt ausführen' })).toHaveCount(0);
  });
  for (const width of [1440, 360, 320]) await step(width + 'px layout, focus and no horizontal overflow', async () => {
    await page.setViewportSize({ width, height: 950 });
    await expect(page.getByRole('heading', { name: 'QA Lokalvertrag' })).toBeVisible();
    await page.getByRole('heading', { name: 'Verbindungen und Vorgänge' }).scrollIntoViewIfNeeded();
    const overflow = await page.evaluate(() => ({
      actual: document.documentElement.scrollWidth, width: window.innerWidth,
    }));
    assert.ok(overflow.actual <= overflow.width + 1, 'Horizontal overflow: ' + JSON.stringify(overflow));
    const picker = page.getByRole('button', { name: /QA Lokalvertrag/ });
    await picker.focus(); await expect(picker).toBeFocused();
    const image = 'connections-' + width + '.png';
    await page.screenshot({ path: path.join(out, image), fullPage: true });
    report.screenshots.push(image);
  });
  await step('A read-only account sees history but no mutation controls', async () => {
    const other = await browser.newContext({ viewport: { width: 360, height: 800 } });
    await other.addInitScript(id =>
      localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })),
    process.env.QA_READER_ID);
    const reader = await other.newPage();
    try {
      await login(reader, 'steuerberater');
      await reader.goto(base.origin + '/integration-connections');
      await expect(reader.getByRole('heading', { name: 'Verbindungen und Vorgänge' })).toBeVisible();
      await expect(reader.getByRole('button', { name: 'Verbindung anlegen' })).toHaveCount(0);
      await reader.getByRole('button', { name: /QA Lokalvertrag/ }).click();
      await expect(reader.getByRole('heading', { name: 'QA Lokalvertrag' })).toBeVisible();
      await expect(reader.getByRole('button', { name: 'Vorschau erstellen' })).toHaveCount(0);
      await expect(reader.getByRole('button', { name: 'Verbindung bearbeiten' })).toHaveCount(0);
    } finally { await other.close(); }
  });
  assert.deepEqual(report.errors, []);
} finally {
  await context?.close();
  await api?.dispose();
  await browser.close();
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(report, null, 2));
}
console.log('CONNECTION_BROWSER_PASSED=' + report.checks.length);
