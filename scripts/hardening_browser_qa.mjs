// Disposable loopback QA only: real Chromium, task actions, and local SMTP sink.
// No message leaves this process. Same QA_* environment as party_workspace_browser_qa.mjs.
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const base = new URL(process.env.QA_BASE_URL || 'about:blank');
if (process.env.QA_ALLOW_TEST_WRITES !== '1' || !['http:', 'https:'].includes(base.protocol)
  || !['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname) || base.username || base.password
  || base.pathname !== '/' || base.search || base.hash || !process.env.QA_PASSWORD) throw Error('Explicit disposable loopback QA configuration required');
if (!path.isAbsolute(process.env.QA_PLAYWRIGHT_PATH || '')) throw Error('QA_PLAYWRIGHT_PATH must be absolute');
const { chromium, request, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
const out = path.resolve('artifacts/hardening-browser');
await fs.mkdir(out, { recursive: true });
const results = { checks: [], errors: [], screenshots: [] };
const commands = [], messages = [], sockets = new Set();
const sink = net.createServer(socket => {
  sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
  socket.write('220 loopback-synthetic-qa\r\n');
  let buffer = '', data = null;
  socket.on('data', chunk => {
    buffer += chunk.toString();
    while (buffer.includes('\r\n')) {
      const end = buffer.indexOf('\r\n'), line = buffer.slice(0, end); buffer = buffer.slice(end + 2);
      if (data !== null) {
        if (line === '.') { messages.push(data); data = null; socket.write('250 stored only in QA memory\r\n'); }
        else data += line + '\r\n';
        continue;
      }
      commands.push(line);
      if (/^(EHLO|HELO)/i.test(line)) socket.write('250-loopback\r\n250 SIZE 1000000\r\n');
      else if (/^(NOOP|MAIL FROM:|RCPT TO:|RSET)/i.test(line)) socket.write('250 OK\r\n');
      else if (line.toUpperCase() === 'DATA') { data = ''; socket.write('354 End with dot\r\n'); }
      else if (line.toUpperCase() === 'QUIT') socket.end('221 Bye\r\n');
      else socket.write('502 Unsupported\r\n');
    }
  });
});
let browser, api, taskId, configured = false, expectedHistoryCount;
async function step(name, fn) {
  try { await fn(); results.checks.push({ name, passed: true }); console.log('PASS', name); }
  catch (error) { results.checks.push({ name, passed: false, error: error.message }); throw error; }
}
async function apiCall(method, url, data) {
  const response = await api.fetch('/api/v1' + url, { method, data });
  assert.ok(response.ok(), `${method} ${url}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function login(username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const response = await api.post('/api/v1/auth/login', { data: { username, password: process.env.QA_PASSWORD } });
  assert.equal(response.status(), 200);
  const tokens = await response.json();
  const profile = await api.get('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + tokens.access_token } });
  const { id } = await profile.json();
  await context.addInitScript(id => {
    if (window.top !== window.self) return;
    localStorage.setItem('locale', 'de-DE'); localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true }));
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style');
      style.textContent = '*, *::before, *::after { animation: none !important; transition: none !important; }';
      document.head.appendChild(style);
    }, { once: true });
  }, id);
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => results.errors.push(error.message));
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  return page;
}
try {
  await new Promise((resolve, reject) => { sink.once('error', reject); sink.listen(0, '127.0.0.1', resolve); });
  browser = await chromium.launch({ channel: 'chromium', headless: true, timeout: 15000 });
  api = await request.newContext({ baseURL: base.origin, timeout: 15000 });
  const response = await api.post('/api/v1/auth/login', { data: { username: process.env.QA_OWNER || 'mat.thias', password: process.env.QA_PASSWORD } });
  assert.equal(response.status(), 200);
  const { access_token } = await response.json();
  await api.dispose();
  api = await request.newContext({ baseURL: base.origin, timeout: 15000, extraHTTPHeaders: { Authorization: 'Bearer ' + access_token } });
  const original = await apiCall('GET', '/integrations/email');
  assert.equal(Object.keys(original.config).length, 0, 'Requires a fresh integration settings store; never replaces existing credentials');
  expectedHistoryCount = (await apiCall('GET', '/integrations/email/history?limit=1')).total + 2;
  const page = await login(process.env.QA_OWNER || 'mat.thias');
  const marker = 'QA-Hardening-' + Date.now();
  const task = await apiCall('POST', '/tasks', { title: marker, status: 'open', priority: 'medium' }); taskId = task.id;
  await step('Task quick completion and reopening persist through API', async () => {
    await page.goto(base.origin + '/tasks');
    await page.locator('.search-input').fill(marker);
    const row = page.locator('tbody tr').filter({ hasText: marker });
    await row.getByRole('button', { name: 'Erledigen', exact: true }).click();
    await expect(row.getByRole('button', { name: 'Wiederöffnen', exact: true })).toBeVisible();
    assert.equal((await apiCall('GET', '/tasks/' + taskId)).status, 'completed');
    await row.getByRole('button', { name: 'Wiederöffnen', exact: true }).click();
    await expect(row.getByRole('button', { name: 'Erledigen', exact: true })).toBeVisible();
    assert.equal((await apiCall('GET', '/tasks/' + taskId)).status, 'open');
  });
  await page.goto(base.origin + '/integrations');
  const card = page.getByRole('region', { name: 'E-Mail (SMTP)', exact: true });
  await step('Configure actual loopback SMTP via UI', async () => {
    await card.getByLabel('Absender', { exact: true }).fill('sender@example.invalid');
    await card.getByLabel('SMTP-Server', { exact: true }).fill('127.0.0.1');
    await card.getByLabel('SMTP-Port', { exact: true }).fill(String(sink.address().port));
    await card.getByLabel('STARTTLS', { exact: true }).uncheck();
    await card.getByRole('button', { name: 'Konfiguration speichern', exact: true }).click(); configured = true;
    await expect(card.getByRole('status')).toContainText('Konfiguration gespeichert');
    assert.equal((await apiCall('GET', '/integrations/email')).config.smtp_host, '127.0.0.1');
  });
  await step('Connection check performs NOOP and sends zero messages', async () => {
    await card.getByLabel('Aktion', { exact: true }).selectOption('check_connection');
    await card.getByRole('button', { name: 'Aktion ausführen', exact: true }).click();
    await expect(card.getByRole('status')).toContainText('keine Nachricht versendet');
    assert.equal(messages.length, 0); assert.ok(commands.some(line => line.toUpperCase() === 'NOOP'));
    assert.ok(!commands.some(line => /^MAIL FROM:/i.test(line)));
  });
  await step('Explicit recipient reaches only local SMTP sink and is journaled', async () => {
    await card.getByLabel('Aktion', { exact: true }).selectOption('send');
    await expect(card.getByRole('button', { name: 'E-Mail versenden', exact: true })).toBeDisabled();
    await card.getByLabel('Empfänger', { exact: true }).fill('recipient@example.invalid');
    await card.getByLabel('Betreff', { exact: true }).fill('Synthetic loopback test');
    await card.getByLabel('Nachricht', { exact: true }).fill('Only retained in this test process.');
    await card.getByRole('button', { name: 'E-Mail versenden', exact: true }).click();
    await expect(card.getByRole('status')).toContainText('E-Mail versendet');
    assert.equal(messages.length, 1); assert.match(messages[0], /To: recipient@example.invalid/);
    await card.getByRole('button', { name: 'Verlauf anzeigen', exact: true }).click();
    await expect(card).toContainText(`${expectedHistoryCount} protokollierte Aktionen`);
    const history = await apiCall('GET', '/integrations/email/history?limit=20');
    assert.equal(history.total, expectedHistoryCount); assert.ok(history.items.slice(0, 2).every(item => item.success));
  });
  for (const width of [1440, 360, 320]) {
    for (const route of ['integrations', 'tasks']) {
      await step(`${route} ${width}px without document overflow`, async () => {
        await page.setViewportSize({ width, height: 1000 }); await page.goto(base.origin + '/' + route);
        await expect(page.locator('h1:visible')).toBeVisible();
        if (route === 'integrations') await expect(card).toBeVisible();
        else await expect(page.locator('.data-table-wrapper')).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        const sizes = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }));
        assert.ok(sizes.content <= sizes.width + 1, JSON.stringify(sizes));
        const file = path.join(out, `${route}-${width}.png`); await page.screenshot({ path: file }); results.screenshots.push(file);
      });
    }
  }
  await step('Read-only integration page has history but no write actions', async () => {
    const reader = await login(process.env.QA_READONLY || 'stb.hofmann');
    await reader.goto(base.origin + '/integrations');
    await expect(reader.getByText('Nur Lesezugriff').first()).toBeVisible();
    await expect(reader.getByRole('button', { name: 'Konfiguration speichern' })).toHaveCount(0);
    await expect(reader.getByRole('button', { name: 'Aktion ausführen' })).toHaveCount(0);
    await reader.getByRole('region', { name: 'E-Mail (SMTP)', exact: true }).getByRole('button', { name: 'Verlauf anzeigen' }).click();
    await expect(reader.getByText(`${expectedHistoryCount} protokollierte Aktionen`)).toBeVisible();
  });
  assert.deepEqual(results.errors, []);
} catch (error) { results.failure = error.message; process.exitCode = 1; console.error(error); }
finally {
  if (api) {
    try {
      if (taskId) await apiCall('DELETE', '/tasks/' + taskId);
      if (configured) {
        const integration = await apiCall('GET', '/integrations/email');
        await apiCall('PUT', '/integrations/email/config', { config: Object.fromEntries(Object.keys(integration.config).map(key => [key, null])) });
      }
    } catch (error) { results.cleanupError = error.message; process.exitCode = 1; }
    await api.dispose();
  }
  for (const socket of sockets) socket.destroy();
  if (sink.listening) await new Promise(resolve => sink.close(resolve));
  if (browser) await browser.close();
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ passed: results.checks.filter(x => x.passed).length, failed: results.checks.filter(x => !x.passed).length, errors: results.errors.length }));
}
