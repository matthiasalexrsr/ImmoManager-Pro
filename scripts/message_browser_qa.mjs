// Real browser acceptance against an owned, synthetic loopback installation only.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || ['8000', '8765'].includes(base.port)
    || base.pathname !== '/' || base.username || process.env.QA_ALLOW_TEST_WRITES !== '1'
    || !process.env.QA_PASSWORD || !process.env.QA_THREAD_A || !process.env.QA_THREAD_B) {
  throw new Error('An explicitly owned synthetic loopback installation is required.');
}
const { chromium, request, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
const out = path.resolve(process.env.QA_OUTPUT);
await fs.mkdir(out, { recursive: true });
const a = process.env.QA_THREAD_A, b = process.env.QA_THREAD_B;
const result = { syntheticOnly: true, checks: [], errors: [], screenshots: [], seededMessages: 10060 };
const browser = await chromium.launch({ channel: 'chromium', headless: true });
result.browserVersion = browser.version();
let api, context, page;
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function call(method, route, data) {
  const response = await api.fetch(`/api/v1${route}`, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  try { await action(); result.checks.push({ name, passed: true }); console.log('PASS ' + name); }
  catch (error) {
    result.checks.push({ name, passed: false, error: String(error) });
    await page?.screenshot({ path: path.join(out, `failure-${result.checks.length}.png`), fullPage: true }).catch(() => {});
    throw error;
  } finally { await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2)); }
}
async function login(target, username = 'owner') {
  await target.goto(base.origin + '/login');
  await target.locator('input[autocomplete="username"]').fill(username);
  await target.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await target.locator('form button[type="submit"]').click();
  await target.waitForURL(url => url.pathname === '/');
  const later = target.getByRole('button', { name: 'Später', exact: true });
  if (await later.isVisible().catch(() => false)) await later.click();
}
async function openThreads(target = page) {
  await target.goto(base.origin + '/messages');
  await target.getByRole('button', { name: /^Konversationen/ }).click();
}
const row = id => page.locator('.messages-sidebar .message-item[role="button"]').filter({ hasText: id === a ? 'Vorgang A' : 'Vorgang B' });
async function choose(id) { await row(id).click(); }
async function ready(id) {
  await expect(page.getByRole('heading', { name: id === a ? /Vorgang A/ : /Vorgang B/ })).toBeVisible();
  await expect(page.locator('.thread-messages')).toHaveAttribute('aria-busy', 'false');
}
const body = () => page.locator('#thread-reply');
const messageBodies = () => page.locator('.thread-message-body');
const getPage = id => call('GET', `/messages/threads/${id}/page?limit=100`);
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const loginResponse = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(loginResponse.ok(), 'Synthetic owner login failed');
  const tokens = await loginResponse.json(); await setup.dispose();
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${tokens.access_token}` } });
  const profile = await call('GET', '/auth/me');
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true }));
  }, profile.id);
  page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => result.errors.push(String(error)));

  await step('Real login, bounded 100-row rendering and complete server count beyond 10,000', async () => {
    await login(page); await openThreads(); await choose(a); await ready(a);
    await expect(messageBodies()).toHaveCount(100);
    await expect(page.locator('.thread-pagination')).toContainText('10057 Nachrichten insgesamt');
    const values = await messageBodies().allTextContents();
    assert.equal(values[0], 'SYN-A-Inhalt-009957'); assert.equal(values.at(-1), 'SYN-A-Inhalt-010056');
    const server = await getPage(a); assert.equal(server.total, 10057); assert.equal(server.items.length, 100);
  });

  await step('Older/newer keyset pages stay bounded and retain the chosen draft', async () => {
    await body().fill('Entwurf A bleibt beim Blättern');
    await page.getByRole('button', { name: 'Ältere Nachrichten', exact: true }).click();
    await expect(page.locator('.thread-pagination')).toContainText('Seite 2'); await ready(a);
    assert.equal((await messageBodies().allTextContents()).at(-1), 'SYN-A-Inhalt-009956');
    await expect(messageBodies()).toHaveCount(100);
    await page.getByRole('button', { name: 'Neuere Nachrichten', exact: true }).click();
    await expect(page.locator('.thread-pagination')).toContainText('Seite 1'); await ready(a);
    await expect(body()).toHaveValue('Entwurf A bleibt beim Blättern');
  });

  await step('A delayed A response cannot replace B or carry its reply text across', async () => {
    await choose(b); await ready(b); await body().fill('Unabhängiger Entwurf B');
    const held = deferred(), fetched = deferred(), delivered = deferred();
    const routePattern = `**/api/v1/messages/threads/${a}/page?*`;
    await page.route(routePattern, async route => {
      const response = await route.fetch(); fetched.resolve(); await held.promise;
      await route.fulfill({ response }).catch(() => {}); delivered.resolve();
    });
    await choose(a); await fetched.promise;
    await expect(messageBodies()).toHaveCount(0);
    await choose(b); await ready(b);
    held.resolve(); await delivered.promise;
    await expect(page.getByRole('heading', { name: /Vorgang B/ })).toBeVisible();
    assert.ok((await messageBodies().allTextContents()).every(value => value.startsWith('SYN-B-')));
    await expect(body()).toHaveValue('Unabhängiger Entwurf B');
    await page.unroute(routePattern); await choose(a); await ready(a);
    await expect(body()).toHaveValue('Entwurf A bleibt beim Blättern');
  });

  await step('Late real committed send acknowledgement stays with A and preserves B draft', async () => {
    const before = (await getPage(a)).total;
    const held = deferred(), committed = deferred(), delivered = deferred();
    const pattern = `**/api/v1/messages/threads/${a}/messages`;
    let saved;
    await page.route(pattern, async route => {
      const response = await route.fetch(); assert.equal(response.status(), 201);
      saved = await response.json(); committed.resolve(); await held.promise;
      await route.fulfill({ response }); delivered.resolve();
    });
    await body().fill('Browser-Nachricht A mit später Bestätigung');
    await page.getByRole('button', { name: 'Senden', exact: true }).click(); await committed.promise;
    await choose(b); await ready(b); await body().fill('Neuer Entwurf B nach A-Sendung');
    held.resolve(); await delivered.promise;
    await expect(page.getByRole('heading', { name: /Vorgang B/ })).toBeVisible();
    await expect(body()).toHaveValue('Neuer Entwurf B nach A-Sendung');
    const after = await getPage(a); assert.equal(after.total, before + 1);
    assert.equal(after.items.filter(item => item.id === saved.id).length, 1);
    await page.unroute(pattern); await choose(a); await ready(a);
    await expect(body()).toHaveValue('');
    await expect(page.getByText('Browser-Nachricht A mit später Bestätigung', { exact: true })).toBeVisible();
  });

  await step('Lost success response reconciles the exact command once without discarding new text', async () => {
    const before = (await getPage(a)).total;
    const payloads = [];
    const pattern = `**/api/v1/messages/threads/${a}/messages`;
    await page.route(pattern, async route => {
      const attempt = payloads.push(route.request().postDataJSON());
      const response = await route.fetch(); assert.equal(response.status(), 201);
      // The real application has committed; emulate a proxy losing its response.
      // Do not use Chromium's connection-abort retry behavior as the test oracle.
      if (attempt === 1) await route.fulfill({ status: 502, contentType: 'application/json',
        body: JSON.stringify({ detail: 'Die bereits gespeicherte Antwort ging am Pr?fproxy verloren.' }) });
      else await route.fulfill({ response });
    });
    await body().fill('Nur einmal speichern trotz verlorener Bestätigung');
    await page.getByRole('button', { name: 'Senden', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Speicherung abgleichen', exact: true })).toBeVisible();
    assert.equal((await getPage(a)).total, before + 1);
    await body().fill('Neue Antwort während des Abgleichs');
    await page.getByRole('button', { name: 'Speicherung abgleichen', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Speicherung abgleichen', exact: true })).toHaveCount(0);
    await ready(a); await expect(body()).toHaveValue('Neue Antwort während des Abgleichs');
    assert.equal(payloads.length, 2); assert.deepEqual(payloads[0], payloads[1]);
    assert.equal((await getPage(a)).total, before + 1);
    await page.unroute(pattern);
  });

  await step('A real failed page is distinguishable from an empty thread and can be retried', async () => {
    const pattern = `**/api/v1/messages/threads/${b}/page?*`;
    await page.route(pattern, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetischer Seitenausfall' }) }));
    await choose(b); await expect(page.getByRole('alert')).toContainText('Synthetischer Seitenausfall');
    await expect(page.getByText(/Noch keine Nachrichten/)).toHaveCount(0);
    await page.unroute(pattern);
    await page.getByRole('button', { name: 'Nachrichten erneut laden', exact: true }).click(); await ready(b);
    await expect(messageBodies()).toHaveCount(3); await expect(body()).toHaveValue('Neuer Entwurf B nach A-Sendung');
  });

  for (const width of [1440, 360, 320]) await step(`Loaded ${width}px layout and keyboard focus`, async () => {
    await page.setViewportSize({ width, height: 1000 });
    await row(a).focus(); await page.keyboard.press('Enter'); await ready(a);
    await expect(messageBodies()).toHaveCount(100);
    await expect(page.getByRole('heading', { name: /Vorgang A/ })).toBeVisible();
    const overflow = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, window: innerWidth }));
    assert.ok(overflow.doc <= overflow.window + 1, `${width}px horizontal overflow: ${JSON.stringify(overflow)}`);
    await body().focus(); await expect(body()).toBeFocused();
    const editorBounds = await body().boundingBox();
    assert.ok(editorBounds && editorBounds.width >= 200 && editorBounds.height >= 100,
      `The reply editor is not usable at ${width}px: ${JSON.stringify(editorBounds)}`);
    await expect(row(a)).toContainText('10059 Nachrichten');
    await page.evaluate(() => window.scrollTo(0, 0));
    const filename = `messages-${width}.png`;
    await page.screenshot({ path: path.join(out, filename), fullPage: true });
    result.screenshots.push(filename);
  });

  await step('Read-only user can page the authorized thread but has no send/create controls', async () => {
    const readerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await readerContext.addInitScript(id => localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })), process.env.QA_READONLY_ID);
    const readerPage = await readerContext.newPage(); await login(readerPage, 'steuerberater'); await openThreads(readerPage);
    await readerPage.locator('.message-item[role="button"]').filter({ hasText: 'Vorgang A' }).click();
    await expect(readerPage.locator('.thread-message')).toHaveCount(100);
    await expect(readerPage.getByRole('button', { name: 'Senden', exact: true })).toHaveCount(0);
    await expect(readerPage.getByRole('button', { name: /Neue Konversation/ })).toHaveCount(0);
    await readerContext.close();
  });

  await step('Changing the account in another tab removes the former private draft and conversation', async () => {
    await body().fill('ALTER PRIVATER ENTWURF DARF NICHT BLEIBEN');
    const second = await context.newPage();
    await second.addInitScript(id => localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })), process.env.QA_OTHER_ID);
    await login(second, 'verwalter');
    await expect(page.locator('#thread-reply')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: /Vorgang A/ })).toHaveCount(0);
    assert.equal(await page.locator('#thread-reply').count(), 0);
    await second.close();
  });
  assert.deepEqual(result.errors, []);
} finally {
  await context?.close(); await api?.dispose(); await browser.close();
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2));
}
console.log(`MESSAGE_BROWSER_PASSED=${result.checks.length}`);
