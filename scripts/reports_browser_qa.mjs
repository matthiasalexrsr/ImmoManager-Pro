import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1'
  || !process.env.QA_PASSWORD || !process.env.QA_PLAYWRIGHT_PATH) throw Error('Owned synthetic application required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], pages: [], page_errors: [], server_errors: [], external: [], expected_errors: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let api, context, page;
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  try { await action(); report.checks.push({ name, ok: true }); console.log('PASS ' + name); }
  catch (error) {
    report.checks.push({ name, ok: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    if (page) await fs.writeFile(path.join(output, 'failure-dom.html'), await page.content());
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function fits() {
  const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(size.document <= size.viewport + 1, `Page overflow ${JSON.stringify(size)}`);
}
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const login = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok());
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + (await login.json()).access_token } });
  await setup.dispose();
  const owner = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Auswertungen' });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Quellenhaus', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'QA Quellenwohnung', unit_type: 'flat', cold_rent: 100 });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Quellenpartei' });
  const contract = await call('POST', '/contracts', { contract_number: 'QA-Quellenvertrag', property_id: property.id,
    unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-01-01', status: 'active' });
  const account = await call('POST', '/accounts', { portfolio_id: portfolio.id, name: 'QA Quellenbank', account_type: 'bank', opening_balance: 1000 });
  const expense = await call('POST', '/bookings', { account_id: account.id, property_id: property.id,
    booking_date: '2026-01-10', amount: -20, payment_text: 'QA Kostenbeleg' });
  await call('POST', '/bookings', { account_id: account.id, property_id: property.id,
    booking_date: '2026-01-10', amount: 42, payment_text: 'QA Zinsbeleg' });
  await call('POST', '/bookings', { account_id: account.id, property_id: property.id, unit_id: unit.id, tenant_id: tenant.id,
    booking_date: '2026-02-01', amount: 300, payment_text: 'QA Vorauszahlung drei Monate' });
  await call('POST', '/invoices', { property_id: property.id, supplier: 'QA stornierte Rechnung',
    invoice_date: '2026-01-01', net_amount: 400, gross_amount: 400, status: 'cancelled' });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', acceptDownloads: true });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })); }, owner.id);
  page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror', error => report.page_errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /(?:Content.Security.Policy|ErrorBoundary caught:)/i.test(message.text())) report.page_errors.push(`UI console: ${message.text()}`); });
  page.on('response', response => { if (response.status() >= 500) report.server_errors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && url.origin !== base.origin) { report.external.push(url.origin); return route.abort(); }
    return route.continue();
  });
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  const route = kind => '/reports?' + new URLSearchParams({ kind, as_of: '2026-01-15', portfolio_id: portfolio.id,
    ...(kind !== 'liquidity-v2' ? { date_from: '2026-01-01', date_to: kind === 'cash-v2' ? '2026-01-31' : '2026-03-31' } : {}) });
  async function calculate(kind) {
    await page.goto(base.origin + route(kind));
    await expect(page.getByRole('button', { name: 'Berechnen', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Berechnen', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Berechneter Bericht' })).toBeVisible();
  }
  const metric = label => page.locator('.finance-result-metric').filter({ has: page.locator('span').filter({ hasText: new RegExp('^' + label + '$') }) });
  await step('Cash totals and full-period booking drilldown agree with underlying sources', async () => {
    await calculate('cash-v2');
    await expect(metric('Einnahmen')).toContainText('42,00');
    await expect(metric('Ausgaben')).toContainText('20,00');
    await expect(metric('Saldo')).toContainText('22,00');
    await metric('Ausgaben').getByRole('link').click();
    await page.waitForURL(url => url.pathname === '/bookings');
    assert.equal(new URL(page.url()).searchParams.get('portfolio_id'), portfolio.id);
    assert.equal(new URL(page.url()).searchParams.get('date_to'), '2026-01-31');
    await expect(page.locator('.data-table tbody')).toContainText('QA Kostenbeleg');
    await expect(page.locator('.data-table tbody')).not.toContainText('QA Zinsbeleg');
    await calculate('cash-v2');
    await page.getByRole('link', { name: 'QA Kostenbeleg', exact: true }).click();
    await page.waitForURL(url => url.searchParams.get('booking_id') === expense.id);
  });
  await step('Cancelled invoices contribute no expense and rental sources open the original contract', async () => {
    await calculate('performance-period-v2');
    await expect(metric('Kosten')).toContainText('20,00');
    await expect(metric('Periodenergebnis')).toContainText('322,00');
    await page.getByRole('button', { name: 'Quellen für 2026-02 anzeigen' }).click();
    const source = page.locator('.finance-sources a').filter({ hasText: 'Sollwarmmiete' });
    await source.click();
    await page.waitForURL(url => url.searchParams.get('contract_id') === contract.id);
    await expect(page.getByText('QA-Quellenvertrag', { exact: true }).first()).toBeVisible();
  });
  await step('Future prepayment reserves all months and opening evidence opens the exact account', async () => {
    await calculate('liquidity-v2');
    await expect(metric('Anfangssaldo')).toContainText('1.022,00');
    await expect(metric('Endsaldo Szenario')).toContainText('1.322,00');
    await page.getByLabel('Quellen durchsuchen').fill('ausgeblendeter Treffer');
    await metric('Anfangssaldo').getByRole('button').click();
    await expect(page.getByLabel('Berechnungsgrundlage')).toHaveValue('opening');
    await expect(page.getByLabel('Quellen durchsuchen')).toHaveValue('');
    await page.getByRole('link', { name: 'Eröffnungssaldo QA Quellenbank' }).click();
    await page.waitForURL(url => url.pathname === '/accounts' && url.searchParams.get('focus_id') === account.id);
    await expect(page.locator('.data-table tbody')).toContainText('QA Quellenbank');
  });
  await step('Scenario additions and the separate basis evidence stay distinct', async () => {
    await calculate('liquidity-v2');
    await page.getByRole('button', { name: 'Zahlung ergänzen' }).click();
    await page.getByLabel('Bezeichnung 1', { exact: true }).fill('QA Zusatzkosten');
    await page.getByLabel('Betrag 1', { exact: true }).fill('-10');
    await page.getByRole('button', { name: 'Berechnen', exact: true }).click();
    await expect(metric('Endsaldo Szenario')).toContainText('1.312,00');
    await expect(metric('Endsaldo Basis')).toContainText('1.322,00');
    await metric('Endsaldo Basis').getByRole('button').click();
    await expect(page.locator('.finance-sources')).not.toContainText('QA Zusatzkosten');
    await metric('Endsaldo Szenario').getByRole('button').click();
    await expect(page.locator('.finance-sources')).toContainText('QA Zusatzkosten');
    for (const format of ['JSON', 'CSV', 'PDF']) {
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: format + ' herunterladen' }).click();
      const download = await downloadPromise;
      await download.saveAs(path.join(output, 'finance-scenario.' + format.toLowerCase()));
      assert.equal(await download.failure(), null);
    }
  });
  await step('Partial report responses are rejected with retained inputs and can be retried', async () => {
    await page.route('**/api/v1/reports/v2/preview?*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ monthly: [] }) }));
    await page.getByRole('button', { name: 'Berechnen', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Berichtsantwort ist unvollständig');
    await expect(page.getByRole('button', { name: 'PDF herunterladen' })).toBeDisabled();
    await expect(page.getByLabel('Bezeichnung 1', { exact: true })).toHaveValue('QA Zusatzkosten');
    await page.unroute('**/api/v1/reports/v2/preview?*');
    await page.getByRole('button', { name: 'Berechnen', exact: true }).click();
    await expect(metric('Endsaldo Szenario')).toContainText('1.312,00');
  });
  await step('Dashboard category statistics open their underlying uncategorized bookings', async () => {
    await page.goto(base.origin + '/');
    await page.getByRole('button', { name: 'Analyse', exact: true }).click();
    const table = page.getByRole('table', { name: 'Alle Buchungskategorien mit Vorzeichen' });
    await expect(table).toBeVisible();
    await table.getByRole('link', { name: 'Ohne Kategorie', exact: true }).click();
    await page.waitForURL(url => url.pathname === '/bookings' && url.searchParams.get('flow') === 'no_category');
    await expect(page.locator('.data-table tbody')).toContainText('QA Kostenbeleg');
  });
  await step('Reports, statistics and budget views fit desktop and narrow displays', async () => {
    for (const width of [320, 360, 1440]) for (const kind of ['cash-v2', 'performance-period-v2', 'liquidity-v2', 'budget', 'dashboard-analysis']) {
      await page.setViewportSize({ width, height: 1000 });
      if (kind === 'budget') { await page.goto(base.origin + '/budgets'); await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible(); }
      else if (kind === 'dashboard-analysis') {
        await page.goto(base.origin + '/');
        await page.getByRole('button', { name: 'Analyse', exact: true }).click();
        await expect(page.getByRole('table', { name: 'Alle Buchungskategorien mit Vorzeichen' })).toBeVisible();
      }
      else await calculate(kind);
      await fits();
      report.pages.push({ route: kind, width, ok: true });
      if (kind !== 'budget') await page.screenshot({ path: path.join(output, `${kind}-${width}.png`), fullPage: true });
    }
  });
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.server_errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
