/** Entire application and real cross-module office workflows, on a new synthetic server only. */
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
const report = { synthetic_only: true, checks: [], pages: [], page_errors: [], server_errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let api, context, page;
let current = 'setup';
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  current = name;
  try { await action(); report.checks.push({ name, ok: true }); console.log('PASS ' + name); }
  catch (error) {
    report.checks.push({ name, ok: false, phase: current, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function fits() {
  const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  if (size.document > size.viewport + 1) {
    const elements = await page.locator('main *').evaluateAll(nodes => nodes.map(node => {
      const bounds = node.getBoundingClientRect();
      return { tag: node.tagName, class: node.className, text: node.textContent?.trim().slice(0, 100), left: bounds.left, right: bounds.right };
    }).filter(node => node.right > innerWidth + 1 && node.right > node.left).slice(0, 20));
    assert.fail(`${current}: Page-wide overflow: ${JSON.stringify({ ...size, elements })}`);
  }
}
const row = text => page.locator('.data-table tbody tr').filter({ hasText: text });
async function shot(name) { await fits(); await page.screenshot({ path: path.join(output, name) }); }
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const response = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok());
  const token = (await response.json()).access_token;
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + token } });
  await setup.dispose();
  const owner = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Gesamtprüfung' });
  const north = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Nordhaus', property_type: 'residential' });
  const south = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Südhaus', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: north.id, label: 'QA Wohnung Nord', unit_type: 'flat', cold_rent: 600, service_charge_advance: 100 });
  const otherUnit = await call('POST', '/units', { property_id: south.id, label: 'QA Wohnung Süd', unit_type: 'flat', cold_rent: 700 });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Anna Nord', email: 'qa-nord@example.invalid' });
  const otherTenant = await call('POST', '/tenants', { full_name: 'QA Ben Süd' });
  const contract = await call('POST', '/contracts', { contract_number: 'QA-MV-NORD', property_id: north.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2025-01-01', status: 'active' });
  const otherContract = await call('POST', '/contracts', { contract_number: 'QA-MV-SÜD', property_id: south.id, unit_id: otherUnit.id, tenant_id: otherTenant.id, start_date: '2025-01-01', status: 'active' });
  const insurance = await call('POST', '/insurances', { provider: 'QA Gebäudeversicherung', insurance_type: 'building', property_id: north.id, unit_id: unit.id, premium_amount: 123.45 });
  await call('POST', '/tasks', { title: 'QA Reparatur nachfassen', property_id: north.id, due_date: '2026-10-25', status: 'open' });
  const contact = await call('POST', '/contacts', { contact_type: 'supplier', company_name: 'QA Stadtwerke' });
  const account = await call('POST', '/accounts', { portfolio_id: portfolio.id, name: 'QA Hauskonto', account_type: 'bank' });
  const service = await call('POST', '/service-contracts', {
    title: 'QA Strom Nordhaus', contract_type: 'electricity', provider_contact_id: contact.id, start_date: '2025-01-01',
    renewal_mode: 'indefinite', notice_period_value: 1, notice_period_unit: 'month', notice_to: 'month_end',
    locations: [{ property_id: north.id }],
    tariff: { valid_from: '2025-01-01', label: 'QA Stromtarif', advance_amount: 100, advance_interval: 'monthly' },
  });
  const upload = await api.post('/api/v1/files/upload?folder=documents', { multipart: {
    file: { name: 'qa-stromvertrag.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetischer QA-Stromvertrag. Keine echten Vertragsdaten.\n') },
  } });
  assert.ok(upload.ok(), 'Owned document fixture upload failed');
  const file = await upload.json();
  assert.ok(file.file_url);
  const document = await call('POST', '/documents', { title: 'QA Stromvertrag', document_type: 'service_contract', property_id: north.id, file_url: file.file_url });
  await call('POST', `/service-contracts/${service.id}/documents`, { document_id: document.id });
  const candidates = [];
  for (let index = 1; index <= 201; index++) {
    candidates.push(await call('POST', '/bookings', { account_id: account.id, property_id: north.id,
      booking_date: '2025-03-02', amount: -100, payment_text: `QA Abschlag ${index}` }));
  }
  const adjustment = await call('POST', '/rent-adjustments', { contract_id: contract.id,
    adjustment_type: 'index', effective_date: '2026-01-01', previous_rent: 600, new_rent: 630, status: 'applied' });
  const maintenance = await call('POST', '/maintenance', { title: 'QA Heizung prüfen', property_id: north.id, status: 'open', priority: 'medium' });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', locale: 'de-DE' });
  await context.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, owner.id);
  await context.route('**/*', route => {
    const target = new URL(route.request().url());
    if (!['http:', 'https:'].includes(target.protocol) || target.origin === base.origin) return route.continue();
    report.external.push(target.origin + target.pathname); return route.abort('blockedbyclient');
  });
  page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => report.page_errors.push({ page: current, error: String(error) }));
  page.on('response', response => {
    if (response.status() >= 500 && new URL(response.url()).origin === base.origin) report.server_errors.push({ page: current, path: new URL(response.url()).pathname, status: response.status() });
  });
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  const later = page.getByRole('button', { name: 'Später', exact: true });
  if (await later.isVisible().catch(() => false)) await later.click();

  await step('Mieterkonto opens precisely its contracts and can remove the inherited context', async () => {
    await page.goto(`${base.origin}/tenants/${tenant.id}/account`);
    await page.getByRole('link', { name: 'Verträge dieses Mieters', exact: true }).click();
    await expect(row(contract.contract_number)).toBeVisible();
    await expect(row(otherContract.contract_number)).toHaveCount(0);
    await expect(page.getByLabel('Vertragsauswahl')).toContainText(tenant.full_name);
    await shot('contracts-context-1440.png');
    await page.getByRole('button', { name: 'Objekt- und Parteifilter aufheben' }).click();
    await expect(row(otherContract.contract_number)).toBeVisible();
  });
  await step('Applied rent changes update the real rent history, with exact percentage and failed-edit preservation', async () => {
    await page.goto(base.origin + '/rent-adjustments');
    await row(contract.contract_number).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    let dialog = page.getByRole('dialog', { name: 'Mietanpassung bearbeiten' });
    await dialog.getByLabel('Neue Miete (€)', { exact: false }).fill('660');
    await expect(dialog.getByLabel('Änderung (%)')).toHaveValue('10 %');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const saved = await call('GET', `/rent-adjustments/${adjustment.id}`);
    assert.equal(saved.new_rent, 660); assert.equal(saved.increase_percent, 10);
    const before = await call('GET', `/contracts/${contract.id}/rent-periods`);
    assert.equal(before.at(-1).cold_rent, 660); assert.equal(before.length, 2);
    await row(contract.contract_number).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Mietanpassung bearbeiten' });
    await dialog.getByLabel('Wirksamkeitsdatum', { exact: false }).fill('2026-01-15');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog.getByRole('alert').first()).toContainText('Monatsersten');
    assert.deepEqual(await call('GET', `/contracts/${contract.id}/rent-periods`), before);
    await shot('rent-adjustment-validation-1440.png');
    await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
    const discard = dialog.getByRole('button', { name: 'Verwerfen', exact: true });
    if (await discard.isVisible().catch(() => false)) await discard.click();
  });
  await step('Calendar form keeps its property and unit consistent and opens the related unit file', async () => {
    await page.goto(base.origin + '/calendar');
    await page.getByRole('button', { name: 'Neu', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Termin erstellen' });
    await dialog.getByLabel('Titel', { exact: false }).fill('QA Gemeinsame Ablesung');
    await dialog.getByLabel('Typ', { exact: false }).selectOption('meeting');
    await dialog.getByLabel('Datum', { exact: false }).fill('2026-10-25');
    await dialog.getByLabel('Uhrzeit').fill('14:30');
    await dialog.getByLabel('Immobilie').selectOption(north.id);
    await dialog.getByLabel('Einheit (optional)').selectOption(unit.id);
    await dialog.getByLabel('Immobilie').selectOption(south.id);
    await expect(dialog.getByLabel('Einheit (optional)')).toHaveValue('');
    await expect(dialog.getByLabel('Einheit (optional)')).not.toContainText(unit.label);
    await dialog.getByLabel('Einheit (optional)').selectOption(otherUnit.id);
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const event = (await call('GET', '/calendar')).find(item => item.title === 'QA Gemeinsame Ablesung');
    assert.equal(event.unit_id, otherUnit.id); assert.equal(event.property_id, south.id); assert.equal(event.event_time, '14:30');
    const eventRow = row(event.title);
    await expect(eventRow.getByRole('link', { name: otherUnit.label, exact: true })).toHaveAttribute('href', '/units/' + otherUnit.id);
    await shot('calendar-1440.png');
  });
  await step('Insurance form clears incompatible units and saves both references together', async () => {
    await page.goto(base.origin + '/insurances');
    await row(insurance.provider).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Immobilie', { exact: false }).selectOption(south.id);
    await expect(dialog.getByLabel('Einheit (optional)')).toHaveValue('');
    await dialog.getByLabel('Einheit (optional)').selectOption(otherUnit.id);
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const saved = await call('GET', `/insurances/${insurance.id}`);
    assert.equal(saved.property_id, south.id); assert.equal(saved.unit_id, otherUnit.id);
  });
  await step('Object contract offers historic/future years and all 201 actual payment choices', async () => {
    await page.goto(`${base.origin}/service-contracts/${service.id}?tab=finance`);
    const year = page.getByLabel('Jahr', { exact: true });
    await year.fill('2001');
    await expect(page.getByTestId('sc-figures')).toBeVisible();
    await year.fill('2046');
    await expect(page.getByTestId('sc-figures')).toBeVisible();
    await year.fill('2025');
    await expect(page.getByTestId('sc-figures')).toBeVisible();
    await page.getByRole('button', { name: 'Zahlung zuordnen', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Zahlung zuordnen' });
    const selected = dialog.getByLabel('Buchung', { exact: false });
    await expect(selected.locator('option')).toHaveCount(202);
    await selected.selectOption(candidates.at(-1).id);
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const payments = await call('GET', `/service-contracts/${service.id}/payments`);
    assert.equal(payments.length, 1); assert.equal(payments[0].booking_id, candidates.at(-1).id);
    await expect(page.getByRole('link', { name: 'QA Abschlag 201', exact: true })).toHaveAttribute('href', '/bookings?booking_id=' + candidates.at(-1).id);
    await shot('service-finance-1440.png');
    await page.setViewportSize({ width: 360, height: 1000 }); await shot('service-finance-360.png');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base.origin}/service-contracts/${service.id}?tab=documents`);
    await expect(page.getByRole('link', { name: 'Dokumentenakte: QA Stromvertrag' })).toHaveAttribute('href', '/documents?focus_id=' + document.id);
    await shot('service-documents-1440.png');
  });

  const source = await fs.readFile(new URL('../frontend/src/App.jsx', import.meta.url), 'utf8');
  const declared = [...source.matchAll(/<Route path="([^"]+)"/g)].map(match => match[1]);
  const validPaths = declared.filter(route => route !== '*').map(route => new RegExp('^/' + route.replace(/^\//, '').replace(/:[^/]+/g, '[^/]+') + '$'));
  const backendPages = new Set(['/openapi.json', '/docs', '/redoc', '/health']);
  const verifiedBackend = new Set();
  const routes = ['/', ...declared.filter(route => route !== '*' && route !== '/' && route !== '/login' && !route.includes(':')).map(route => '/' + route.replace(/^\//, '')),
    `/properties/${north.id}`, `/units/${unit.id}`, `/tenants/${tenant.id}/account`, `/service-contracts/${service.id}`, `/maintenance/${maintenance.id}`];
  for (const width of [320, 360, 1440]) {
    await step(`All ${routes.length} application pages at ${width}px: visible text, navigation targets, errors and overflow`, async () => {
      await page.setViewportSize({ width, height: 1000 });
      for (const route of routes) {
        current = `${route} (${width}px)`;
        const started = Date.now();
        await page.goto(base.origin + route);
        await page.waitForLoadState('networkidle');
        await fits();
        const text = await page.locator('body').innerText();
        assert.ok(!/\b(?:undefined|NaN|Invalid Date)\b/.test(text), `${current}: broken visible value`);
        const hrefs = await page.locator('a[href]').evaluateAll(links => links.map(link => link.getAttribute('href')));
        for (const href of hrefs) {
          if (!href?.startsWith('/') || href.startsWith('/api/') || href.startsWith('/uploads/')) continue;
          const pathname = new URL(href, base).pathname;
          if (backendPages.has(pathname)) {
            if (!verifiedBackend.has(pathname)) {
              const response = await api.get(pathname);
              assert.ok(response.ok(), `${current}: linked backend page is unavailable: ${pathname}`);
              if (pathname === '/openapi.json') assert.ok((await response.json()).openapi);
              verifiedBackend.add(pathname);
            }
            continue;
          }
          assert.ok(validPaths.some(pattern => pattern.test(pathname)), `${current}: unknown internal page ${pathname}`);
        }
        report.pages.push({ route, width, ok: true, duration_ms: Date.now() - started });
      }
      await shot(`application-last-page-${width}.png`);
    });
  }
  assert.deepEqual(report.page_errors, []);
  assert.deepEqual(report.server_errors, []);
  assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
