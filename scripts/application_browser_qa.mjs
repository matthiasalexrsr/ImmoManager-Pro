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
    if (page) await fs.writeFile(path.join(output, 'failure-dom.html'), await page.content());
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
  const contractDocument = await call('POST', '/documents', { title: 'QA Vertragsanlage Nord', contract_id: contract.id, file_url: file.file_url });
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

  await step('Property, unit and contract files find indirectly assigned documents and open their exact file', async () => {
    await page.goto(`${base.origin}/properties/${north.id}?tab=documents`);
    await page.getByRole('link', { name: contractDocument.title, exact: true }).click();
    await expect(page.getByRole('heading', { name: contractDocument.title, exact: true })).toBeVisible();
    const assignment = page.getByRole('region', { name: 'Zuordnung', exact: true });
    await expect(assignment.getByRole('link', { name: unit.label, exact: true })).toHaveAttribute('href', `/units/${unit.id}`);
    await expect(assignment).toContainText(tenant.full_name);
    await assignment.getByRole('link', { name: unit.label, exact: true }).click();
    await expect(page.getByRole('region', { name: 'Dokumente der Einheit' }).getByRole('link', { name: contractDocument.title })).toBeVisible();
    await page.getByRole('link', { name: 'Dokumente dieser Einheit', exact: true }).click();
    await expect(page.getByLabel('Dokumentauswahl')).toContainText(unit.label);
    await expect(row(contractDocument.title)).toHaveCount(1);
    await expect(row(document.title)).toHaveCount(0);
    await shot('unit-documents-context-1440.png');
  });
  await step('Document assignments use dependent choices and refresh all links after an actual committed save', async () => {
    await page.goto(`${base.origin}/documents/${contractDocument.id}`);
    await page.getByRole('button', { name: 'Zuordnung bearbeiten', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Dokumentzuordnung bearbeiten', exact: true });
    await dialog.getByLabel('Vertrag', { exact: true }).selectOption(otherContract.id);
    await expect(dialog.getByLabel('Immobilie', { exact: true })).toHaveValue(south.id);
    await expect(dialog.getByLabel('Einheit', { exact: true })).toHaveValue(otherUnit.id);
    await expect(dialog.getByLabel('Mieter / Partei', { exact: true })).toHaveValue(otherTenant.id);
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/documents/${contractDocument.id}` && response.request().method() === 'PATCH' && response.ok());
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await saved;
    await expect(dialog).toHaveCount(0);
    const assignment = page.getByRole('region', { name: 'Zuordnung', exact: true });
    await expect(assignment.getByRole('link', { name: south.name, exact: true })).toBeVisible();
    await expect(assignment.getByRole('link', { name: otherUnit.label, exact: true })).toBeVisible();
    await shot('document-assignment-saved-1440.png');
    // Return this owned fixture to its initial, deliberately indirect contract association.
    await call('PATCH', `/documents/${contractDocument.id}`, { property_id: null, unit_id: null, tenant_id: null, contract_id: contract.id });
  });
  await step('Quick views download the current version and preserve the original; mobile dialogs remain usable', async () => {
    await page.goto(`${base.origin}/documents/${contractDocument.id}`);
    const form = page.getByRole('form', { name: 'Neue Fassung hochladen' });
    const changedBytes = Buffer.from('Korrigierte QA Vertragsanlage. Fassung 2 bleibt nachvollziehbar.\n');
    await form.getByLabel('Datei', { exact: true }).setInputFiles({ name: 'qa-vertragsanlage-v2.txt', mimeType: 'text/plain', buffer: changedBytes });
    await form.getByRole('button', { name: 'Als neue Fassung speichern', exact: true }).click();
    await expect(form.getByRole('status')).toContainText('Gespeichert als Fassung 2');
    const versions = await call('GET', `/documents/${contractDocument.id}/work/versions?limit=10`);
    assert.deepEqual(versions.items.map(item => item.number), [2, 1]);
    const original = await api.get(`/api/v1/documents/${contractDocument.id}/work/versions/${versions.items[1].id}/download`);
    assert.ok(original.ok());
    assert.equal((await original.body()).toString(), 'Synthetischer QA-Stromvertrag. Keine echten Vertragsdaten.\n');
    await page.goto(`${base.origin}/documents?contract_id=${contract.id}`);
    await row(contractDocument.title).getByRole('button', { name: 'Dokument ansehen', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: contractDocument.title, exact: true });
    await expect(dialog).toContainText('Aktuelle Fassung 2');
    const downloadEvent = page.waitForEvent('download');
    await dialog.getByRole('button', { name: 'Aktuelle Fassung herunterladen', exact: true }).click();
    const downloaded = await downloadEvent;
    assert.deepEqual(await fs.readFile(await downloaded.path()), changedBytes);
    for (const width of [320, 360, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await shot(`current-document-version-${width}.png`);
      assert.ok(await dialog.getByRole('button', { name: 'Schließen', exact: true }).isVisible());
    }
    await dialog.getByRole('button', { name: 'Schließen', exact: true }).click();
  });

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

  let financialInvoice;
  await step('Invoice list and payment file agree; an older payment beyond the first page can be linked', async () => {
    financialInvoice = await call('POST', '/invoices', { supplier: 'QA Restbetragsprüfung', invoice_number: 'QA-RE-REST',
      property_id: north.id, invoice_date: '2026-01-01', due_date: '2026-12-31', net_amount: 123.45, gross_amount: 123.45 });
    const paid = await call('POST', '/bookings', { account_id: account.id, property_id: north.id,
      booking_date: '2026-01-01', amount: -40, status: 'open', payment_text: 'QA Bereits bezahlt' });
    await call('POST', `/invoices/${financialInvoice.id}/payments`, { booking_id: paid.id, amount: 40 });
    for (let i = 0; i < 26; i++) await call('POST', '/bookings', { account_id: account.id, property_id: north.id,
      booking_date: '2026-01-02', amount: -1, payment_text: 'QA RE-REST Auswahl neuer ' + i });
    const older = await call('POST', '/bookings', { account_id: account.id, property_id: north.id,
      booking_date: '2025-01-01', amount: -100, payment_text: 'QA RE-REST Auswahl älter' });
    await call('POST', '/invoices', { supplier: 'QA Zahlungsnachweis fehlt', invoice_number: 'QA-RE-UNGEKLAERT',
      property_id: north.id, invoice_date: '2026-01-01', net_amount: 90, gross_amount: 90, status: 'paid' });
    await page.goto(base.origin + '/invoices');
    await expect(row('QA-RE-UNGEKLAERT')).toContainText('Ungeklärt');
    await expect(row('QA-RE-UNGEKLAERT')).toContainText('ohne zugeordnete Zahlung');
    await expect(row('QA-RE-REST')).toContainText('83,45');
    await expect(row('QA-RE-REST')).toContainText('40,00');
    await page.getByRole('link', { name: 'QA-RE-REST', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Zahlung zuordnen', exact: true }).click();
    const picker = page.getByRole('dialog', { name: 'Zahlung zuordnen' });
    await expect(picker).toBeVisible();
    await picker.getByRole('searchbox').fill('QA RE-REST Auswahl');
    await picker.getByRole('button', { name: 'Suchen', exact: true }).click();
    await expect(picker.locator('li')).toHaveCount(25);
    await picker.getByRole('button', { name: 'Weitere laden', exact: true }).click();
    await picker.locator('li').filter({ hasText: 'QA RE-REST Auswahl älter' }).getByRole('button', { name: 'Auswählen', exact: true }).click();
    const payment = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Zahlung', exact: true }) });
    await expect(payment.getByLabel('Betrag', { exact: true })).toHaveValue('83.45');
    const savedPayment = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/invoices/${financialInvoice.id}/payments`
      && response.request().method() === 'POST');
    await payment.getByRole('button', { name: 'Speichern', exact: true }).click();
    assert.equal((await savedPayment).status(), 201);
    await expect(payment.locator('ul').getByRole('link', { name: /QA RE-REST Auswahl älter/ })).toBeVisible();
    const details = await call('GET', `/invoices/${financialInvoice.id}/review`);
    assert.equal(details.settlement.paid, 123.45); assert.equal(details.settlement.open, 0);
    const overview = (await call('GET', '/invoices/overview')).find(item => item.id === financialInvoice.id);
    assert.equal(overview.payment_summary.open, 0); assert.equal(overview.payment_summary.paid, 123.45);
    assert.ok(details.payments.some(item => item.booking_id === older.id));
    await page.setViewportSize({ width: 360, height: 1000 });
    await shot('invoice-payments-360.png');
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await step('Invoice receipt checkbox and its complete label remain usable at mobile and desktop widths', async () => {
    const checkbox = page.getByRole('checkbox', { name: 'Umlagefähig', exact: true });
    for (const width of [320, 360, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await checkbox.scrollIntoViewIfNeeded();
      const bounds = await checkbox.evaluate(input => {
        const box = input.getBoundingClientRect(), label = input.closest('label').getBoundingClientRect();
        return { width: box.width, height: label.height, left: label.left, right: label.right, viewport: innerWidth };
      });
      assert.ok(bounds.width <= 32 && bounds.height <= 70 && bounds.left >= 0 && bounds.right <= bounds.viewport,
        'Checkbox label is clipped or unreadable: ' + JSON.stringify(bounds));
      await shot(`invoice-receipt-${width}.png`);
    }
  });
  await step('Tenant and booking files keep the chosen date and open the exact linked source', async () => {
    const incoming = await call('POST', '/bookings', { account_id: account.id, property_id: north.id, unit_id: unit.id,
      tenant_id: tenant.id, booking_date: '2026-02-15', amount: 20, payment_text: 'QA Stichtagszahlung' });
    await page.goto(`${base.origin}/bookings?booking_id=${incoming.id}`);
    await page.getByRole('link', { name: 'Mieterkonto zum Buchungsdatum', exact: true }).click();
    await expect(page.getByLabel('Stichtag', { exact: true })).toHaveValue('2026-02-15');
    await expect(page.getByRole('link', { name: 'Buchungen dieses Mieters', exact: true }))
      .toHaveAttribute('href', `/bookings?tenant_id=${tenant.id}&date_to=2026-02-15`);
    await page.getByRole('link', { name: 'Buchungen dieses Mieters', exact: true }).click();
    await expect(row('QA Stichtagszahlung')).toBeVisible();
    assert.equal(new URL(page.url()).searchParams.get('date_to'), '2026-02-15');
  });
  await step('Statement and claim files form a precise round trip; repeating claim creation never duplicates it', async () => {
    const period = await call('POST', '/billing/periods', { property_id: north.id, label: 'QA Abrechnungsbrücke 2025', start_date: '2025-01-01', end_date: '2025-12-31' });
    const key = await call('POST', '/billing/allocation-keys', { property_id: north.id, name: 'QA Einheitenbrücke', key_type: 'unit_count' });
    await call('POST', '/billing/cost-items', { billing_period_id: period.id, description: 'QA Belegbare Nebenkosten', amount: 120, allocation_key_id: key.id });
    const generated = await call('POST', `/billing/periods/${period.id}/generate`, {});
    const statement = generated.find(item => item.party !== 'vacancy'); assert.ok(statement);
    await call('POST', `/billing/periods/${period.id}/finalize`, {});
    const first = await call('POST', `/billing/periods/${period.id}/create-receivables`, {});
    assert.equal(first.created_receivables, 1);
    assert.equal((await call('POST', `/billing/periods/${period.id}/create-receivables`, {})).created_receivables, 0);
    await page.goto(`${base.origin}/statements?period_id=${period.id}`);
    await page.getByRole('link', { name: 'Forderungen & Guthaben', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Forderungen und Guthaben dieser Einzelabrechnung' })).toBeVisible();
    assert.equal(new URL(page.url()).searchParams.get('statement_id'), statement.id);
    await expect(row('Nebenkostenabrechnung QA Abrechnungsbrücke 2025')).toHaveCount(1);
    await page.getByRole('link', { name: 'Einzelabrechnung öffnen', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('dialog')).toContainText('QA Wohnung Nord');
    assert.equal(new URL(page.url()).searchParams.get('statement_id'), statement.id);
    await shot('statement-source-roundtrip-1440.png');
  });

  const source = await fs.readFile(new URL('../frontend/src/App.jsx', import.meta.url), 'utf8');
  const declared = [...source.matchAll(/<Route path="([^"]+)"/g)].map(match => match[1]);
  const validPaths = declared.filter(route => route !== '*').map(route => new RegExp('^/' + route.replace(/^\//, '').replace(/:[^/]+/g, '[^/]+') + '$'));
  const backendPages = new Set(['/openapi.json', '/docs', '/redoc', '/health']);
  const verifiedBackend = new Set();
  const routes = ['/', ...declared.filter(route => route !== '*' && route !== '/' && route !== '/login' && !route.includes(':')).map(route => '/' + route.replace(/^\//, '')),
    `/properties/${north.id}`, `/units/${unit.id}`, `/tenants/${tenant.id}/account`, `/service-contracts/${service.id}`, `/maintenance/${maintenance.id}`,
    `/invoice-review/${financialInvoice.id}`, `/documents/${contractDocument.id}`];
  for (const width of [320, 360, 1440]) {
    await step(`All ${routes.length} application pages at ${width}px: visible text, navigation targets, errors and overflow`, async () => {
      await page.setViewportSize({ width, height: 1000 });
      const failures = [];
      for (const route of routes) {
        current = `${route} (${width}px)`;
        const started = Date.now();
        try {
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
        } catch (error) {
          const failure = { route, width, ok: false, error: String(error) };
          report.pages.push(failure); failures.push(failure);
          await page.screenshot({ path: path.join(output, `failure-${width}-${route.replace(/[^a-z0-9]/gi, '_')}.png`), fullPage: true });
        }
      }
      assert.deepEqual(failures, [], 'Application pages failed: ' + JSON.stringify(failures));
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
