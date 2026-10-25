// Run only against a disposable local QA server. Credentials are environment-only.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const base = new URL(process.env.QA_BASE_URL || '');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || base.pathname !== '/' || base.username
  || process.env.QA_ALLOW_TEST_WRITES !== '1' || !process.env.QA_PASSWORD || !process.env.QA_PLAYWRIGHT_PATH) {
  throw new Error('Set QA_BASE_URL (loopback origin), QA_ALLOW_TEST_WRITES=1, QA_PASSWORD and QA_PLAYWRIGHT_PATH.');
}
const { chromium, request, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
const out = path.resolve(process.env.QA_OUTPUT || 'artifacts/continuation-20261013/rent-browser');
await fs.mkdir(out, { recursive: true });
const result = { started: new Date().toISOString(), checks: [], errors: [], screenshots: [], syntheticOnly: true };
const browser = await chromium.launch({ channel: 'chromium', headless: true });
result.browserVersion = browser.version();
let api;
const password = process.env.QA_PASSWORD;

async function step(name, action) {
  try { await action(); result.checks.push({ name, passed: true }); console.log(`PASS ${name}`); }
  catch (error) { result.checks.push({ name, passed: false, error: String(error) }); throw error; }
}
async function call(method, resource, data) {
  const response = await api.fetch(`/api/v1${resource}`, { method, data });
  assert.ok(response.ok(), `${method} ${resource}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function login(page, username) {
  await page.goto(`${base.origin}/login`);
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  const later = page.getByRole('button', { name: 'Später', exact: true });
  await later.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
  if (await later.isVisible().catch(() => false)) await later.click();
  await page.goto(`${base.origin}/rent-overview`);
}
async function month(page) {
  await page.getByLabel('Mietmonat', { exact: true }).fill('2026-01');
  await page.getByLabel('Zahlungen bis Stichtag').fill('2026-01-31');
  await expect(page.getByRole('button', { name: 'Eingang buchen', exact: true })).toBeVisible();
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: false });
  result.screenshots.push(`${name}.png`);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Page overflows viewport');
}
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const response = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password } });
  assert.ok(response.ok(), 'QA owner login failed');
  const credentials = await response.json();
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${credentials.access_token}` } });
  await setup.dispose();
  const portfolio = await call('POST', '/portfolios', { name: 'QA Zahlungsprüfung' });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Haus Äußere Straße', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'Wohnung 1', unit_type: 'residential', cold_rent: 500, service_charge_advance: 100 });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Mia Mieterin' });
  const contract = await call('POST', '/contracts', { contract_number: 'QA-MV-1', property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-01-01', status: 'active' });
  const account = await call('POST', '/accounts', { portfolio_id: portfolio.id, name: 'QA Mietkonto', account_type: 'bank' });
  await call('POST', '/auth/users', { username: 'qa-rent-reader', full_name: 'QA Reader', email: 'qa-rent-reader@example.invalid', password, role: 'readonly', portfolio_access: 'selected', portfolio_ids: [portfolio.id] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.on('pageerror', error => result.errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /Content.Security.Policy/i.test(message.text())) result.errors.push(`CSP: ${message.text()}`); });
  await step('Real login and computed monthly rent', async () => {
    await login(page, 'owner'); await month(page);
    await expect(page.getByText('QA Mia Mieterin', { exact: true })).toBeVisible();
    await screenshot(page, 'rent-overview-1440');
  });
  const fillPayment = async (amount, note) => {
    await page.getByRole('button', { name: 'Eingang buchen', exact: true }).click();
    await page.getByLabel('Zahlungskonto', { exact: true }).selectOption(account.id);
    await page.getByLabel('Zahlungsbetrag (€)', { exact: true }).fill(amount);
    await page.getByLabel('Tatsächlicher Zahlungseingang').fill('2026-01-07');
    await page.getByLabel('Buchungstext / Bemerkung').fill(note);
  };
  await step('Partial payment records cash, date, note and allocation', async () => {
    await fillPayment('200.10', 'QA Teilzahlung · Überweisung');
    await screenshot(page, 'rent-payment-1440');
    await page.getByRole('button', { name: /als Eingang buchen/ }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Zahlung und Vertragszuordnung gespeichert.' })).toBeVisible();
    const bookings = await call('GET', '/bookings');
    assert.equal(bookings.length, 1); assert.equal(bookings[0].amount, 200.10);
    assert.equal(bookings[0].booking_date, '2026-01-07'); assert.equal(bookings[0].payment_text, 'QA Teilzahlung · Überweisung');
    const ledger = await call('GET', '/rent-charges/ledger?month=2026-01&as_of=2026-01-31');
    assert.deepEqual(ledger.totals, { expected: 600, paid: 200.1, outstanding: 399.9, contract_credit: 0 });
  });
  await step('Lost success response survives reload and does not duplicate cash', async () => {
    await fillPayment('100.20', 'QA verlorene Antwort');
    await page.route('**/api/v1/rent-charges/contract-payment', async route => {
      const reply = await route.fetch(); assert.equal(reply.status(), 201);
      await route.abort('failed');
    }, { times: 1 });
    await page.getByRole('button', { name: /als Eingang buchen/ }).click();
    await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
    await page.reload();
    await page.getByRole('button', { name: 'Buchung fortsetzen' }).click();
    await page.getByRole('button', { name: 'Buchung prüfen', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Bereits gebuchte Zahlung gefunden.' })).toBeVisible();
    assert.equal((await call('GET', '/bookings')).length, 2);
    await month(page);
  });
  await step('Confirmed stale rejection can reload and retry a fresh command', async () => {
    await fillPayment('10.30', 'QA nach Konflikt');
    await call('PATCH', `/contracts/${contract.id}`, { contract_number: 'QA-MV-1 aktualisiert' });
    await page.getByRole('button', { name: /als Eingang buchen/ }).click();
    await page.getByRole('button', { name: 'Mietübersicht neu laden', exact: true }).click();
    await fillPayment('10.30', 'QA nach Konflikt');
    await page.getByRole('button', { name: /als Eingang buchen/ }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Zahlung und Vertragszuordnung gespeichert.' })).toBeVisible();
    assert.equal((await call('GET', '/bookings')).length, 3);
  });
  await step('Narrow layouts and keyboard dialog dismissal', async () => {
    for (const width of [360, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await screenshot(page, `rent-overview-${width}`);
      await page.getByRole('button', { name: 'Eingang buchen', exact: true }).click();
      const bounds = await page.getByRole('dialog').boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0
        && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= 1001,
      'Payment dialog must remain within the mobile viewport');
      await screenshot(page, `rent-payment-${width}`);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
    }
  });
  await step('Large aggregate amounts fit compact mobile summary cards', async () => {
    // A layout-only response fixture; no fabricated balance is written to the QA database.
    await page.route('**/api/v1/rent-charges/ledger?*', async route => {
      const response = await route.fetch();
      const data = await response.json();
      data.totals = { expected: 999999999999.99, paid: 999999999999.99,
        outstanding: 999999999999.99, contract_credit: 999999999999.99 };
      await route.fulfill({ response, json: data });
    }, { times: 1 });
    await page.reload();
    await expect(page.locator('.stat-card')).toHaveCount(4);
    assert.ok(await page.locator('.stat-card').evaluateAll(cards => cards.every(card => {
      const value = card.querySelector('.stat-value');
      const outer = card.getBoundingClientRect(); const inner = value.getBoundingClientRect();
      return value.scrollWidth <= value.clientWidth + 1 && inner.right <= outer.right && inner.left >= outer.left;
    })), 'Large amounts overflow their mobile card');
    await screenshot(page, 'rent-large-amounts-320');
  });
  await step('Read-only user sees balances without payment controls', async () => {
    const reader = await browser.newContext({ viewport: { width: 360, height: 1000 } });
    const view = await reader.newPage();
    view.on('pageerror', error => result.errors.push(String(error)));
    await login(view, 'qa-rent-reader');
    await expect(view.getByText('QA Mia Mieterin', { exact: true })).toBeVisible();
    await expect(view.getByRole('button', { name: 'Eingang buchen', exact: true })).toHaveCount(0);
    await screenshot(view, 'rent-readonly-360');
    await reader.close();
  });
  assert.deepEqual(result.errors, []);
  result.status = 'passed';
} catch (error) {
  result.status = 'failed'; result.failure = String(error); console.error(String(error)); process.exitCode = 1;
} finally {
  await api?.dispose();
  try { await browser.close(); result.browserStopped = true; }
  catch (error) { result.browserStopped = false; result.cleanupError = String(error); process.exitCode = 1; }
  result.finished = new Date().toISOString();
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2));
}
