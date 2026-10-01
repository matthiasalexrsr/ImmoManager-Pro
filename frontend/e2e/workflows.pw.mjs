import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

// Every workflow uses the real rendered app and seeded SQL-backed API.
// No requests are intercepted and no business data is replaced with mocks.


async function login(page) {
  await page.goto('/login');
  await page.locator('form input[type="text"]').fill('demo');
  await page.locator('form input[type="password"]').fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  expect(token).toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function api(page, path, headers, data) {
  const response = data === undefined
    ? await page.request.get(`/api/v1${path}`, { headers })
    : await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.json();
}

const money = amount => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);

async function checkMobileWidth(page, testInfo, name) {
  await page.setViewportSize({ width: 390, height: 844 });
  // Screenshot waits for resize layout and finishes the sidebar's finite CSS transition.
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true, animations: 'disabled' });
  await testInfo.attach(name, { path: screenshotPath, contentType: 'image/png' });
  const size = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    overflowing: [...document.querySelectorAll('main, .page, .detail-header, .detail-title, .card, .card-header, .table-header, .step-indicator')]
      .map(element => ({ class: element.className, right: Math.round(element.getBoundingClientRect().right), width: Math.round(element.getBoundingClientRect().width) }))
      .filter(element => element.right > innerWidth),
  }));
  await testInfo.attach(`${name}-layout`, { body: JSON.stringify(size, null, 2), contentType: 'application/json' });
  expect(size.document, `The mobile page must fit the viewport: ${JSON.stringify(size.overflowing)}`).toBeLessThanOrEqual(size.viewport);
}

test('seeded property and contract: partial rent payment survives reload', async ({ page }, testInfo) => {
  const headers = await login(page);
  const properties = await api(page, '/properties', headers);
  const property = properties.find(item => item.name === 'Schönhauser Allee 78');
  expect(property?.city).toBe('Berlin');
  const contracts = await api(page, '/contracts', headers);
  const charges = await api(page, '/rent-charges', headers);
  const charge = charges.find(item => item.status === 'partial' && Number(item.amount_paid) > 0);
  expect(charge).toBeTruthy();
  const contract = contracts.find(item => item.id === charge.contract_id);
  expect(contract.property_id).toBe(property.id);
  expect(contract.contract_number).toMatch(/^MV-\d{4}-\d{3}$/);

  await page.goto('/rent-overview');
  await expect(page.getByRole('heading', { name: 'Mietübersicht', exact: true })).toBeVisible();
  const row = page.getByRole('row').filter({ hasText: contract.contract_number }).filter({ hasText: charge.month });
  await expect(row).toHaveCount(1);
  const total = ['cold_rent', 'service_charge', 'heating_charge', 'other_charges']
    .reduce((sum, key) => sum + Number(charge[key] || 0), 0);
  const beforePaid = Number(charge.amount_paid);
  const amount = 12.34;
  const note = `Browser payment ${randomUUID()}`;
  await row.getByRole('button', { name: 'Zahlung erfassen', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Zahlungsbetrag (€)', { exact: false }).fill(String(amount));
  await dialog.getByLabel('Zahlungsdatum', { exact: false }).fill('2026-01-15');
  await dialog.getByLabel('Bemerkung', { exact: true }).fill(note);
  const saved = page.waitForResponse(response => response.url().endsWith(`/rent-charges/${charge.id}/payments`) && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await saved).status()).toBe(201);
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Zahlung wurde gespeichert.' })).toBeVisible();
  await expect(row.locator('td').nth(5)).toHaveText(money(beforePaid + amount));
  await expect(row.locator('td').nth(6)).toHaveText(money(total - beforePaid - amount));

  await page.reload();
  await expect(row.locator('td').nth(5)).toHaveText(money(beforePaid + amount));
  await expect(row.locator('td').nth(6)).toHaveText(money(total - beforePaid - amount));
  await row.getByRole('button', { name: 'Zahlungshistorie', exact: true }).click();
  const history = page.getByRole('region', { name: 'Zahlungshistorie', exact: true });
  const receiptRow = history.getByRole('row').filter({ hasText: note });
  await expect(receiptRow).toContainText(money(amount));
  const receipts = await api(page, `/rent-charges/${charge.id}/payments`, headers);
  expect(receipts.filter(receipt => receipt.note === note)).toHaveLength(1);
  const persisted = await api(page, `/rent-charges/${charge.id}`, headers);
  expect(Number(persisted.amount_paid)).toBeCloseTo(beforePaid + amount, 2);
  expect(persisted.status).toBe('partial');
  await checkMobileWidth(page, testInfo, 'payment-history-mobile');
});

test('billing draft: blocked preflight becomes ready and generates persisted statements', async ({ page }, testInfo) => {
  const headers = await login(page);
  const properties = await api(page, '/properties', headers);
  const property = properties.find(item => item.name === 'Kastanienallee 42');
  expect(property?.city).toBe('Berlin');
  const key = await api(page, '/billing/allocation-keys', headers, {
    property_id: property.id, name: `Browser area ${randomUUID()}`, key_type: 'area_sqm',
  });
  const today = new Date();
  const start = `${today.getUTCFullYear()}-${String(today.getUTCMonth() + 1).padStart(2, '0')}-01`;
  const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + 1, 0)).toISOString().slice(0, 10);
  const label = `Browser billing ${randomUUID()}`;

  await page.goto('/statements');
  await expect(page.getByRole('heading', { name: 'Nebenkostenabrechnungen', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Neu', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Immobilie', { exact: false }).selectOption(property.id);
  await dialog.getByLabel('Bezeichnung', { exact: false }).fill(label);
  await dialog.getByLabel('Beginn', { exact: false }).fill(start);
  await dialog.getByLabel('Ende', { exact: false }).fill(end);
  const created = page.waitForResponse(response => response.url().endsWith('/billing/periods') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const creation = await created;
  expect(creation.status()).toBe(201);
  const period = await creation.json();
  expect(period.status).toBe('draft');
  await expect(dialog).not.toBeVisible();
  const periodRow = page.getByRole('row').filter({ hasText: property.name }).filter({ hasText: `${start} – ${end}` });
  await periodRow.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
  await expect(page.getByText('Keine Kostenpositionen für diese Periode vorhanden', { exact: true })).toBeVisible();
  const generate = page.getByRole('button', { name: 'Abrechnungen generieren', exact: true });
  await expect(generate).toBeDisabled();
  await page.getByRole('button', { name: 'Neu', exact: true }).click();
  await dialog.getByLabel('Kostenart', { exact: false }).fill('Gebäudereinigung Browsertest');
  await dialog.getByLabel('Betrag (€)', { exact: false }).fill('600.00');
  await dialog.getByLabel('Verteilerschlüssel', { exact: false }).selectOption(key.id);
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText('Bereit zur Generierung', { exact: true })).toBeVisible();
  await expect(generate).toBeEnabled();
  const preflight = await api(page, `/billing/periods/${period.id}/preflight`, headers);
  expect(preflight.has_blockers).toBe(false);
  expect(preflight.metrics.contracts_in_period).toBeGreaterThan(0);
  const generated = page.waitForResponse(response => response.url().endsWith(`/billing/periods/${period.id}/generate`) && response.request().method() === 'POST');
  await generate.click();
  const generation = await generated;
  expect(generation.status()).toBe(201);
  const statements = await generation.json();
  expect(statements).toHaveLength(preflight.metrics.contracts_in_period);
  const savedPeriod = await api(page, `/billing/periods/${period.id}`, headers);
  const owner = savedPeriod.owner_cost_share;
  expect(owner?.policy).toBe('property_units_occupied_days');
  const tenantCents = statements.reduce((sum, statement) => sum + Math.round(Number(statement.total_cost) * 100), 0);
  expect(Math.round(Number(owner.tenant_cost_total) * 100)).toBe(tenantCents);
  expect(Math.round(Number(owner.property_cost_total) * 100)).toBe(60000);
  expect(tenantCents + Math.round(Number(owner.total_amount) * 100)).toBe(60000);
  expect(Math.round(Number(owner.recoverable_vacancy_amount) * 100)
    + Math.round(Number(owner.non_recoverable_amount) * 100)).toBe(Math.round(Number(owner.total_amount) * 100));
  for (const statement of statements) {
    expect(Number(statement.balance)).toBeCloseTo(Number(statement.total_cost) - Number(statement.advance_paid), 2);
  }
  await expect(page.getByRole('heading', { name: 'Einzelabrechnungen pro Einheit', exact: true })).toBeVisible();
  await page.reload();
  await periodRow.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
  const persisted = await api(page, `/billing/statements?billing_period_id=${period.id}`, headers);
  expect(persisted.map(statement => statement.id).sort()).toEqual(statements.map(statement => statement.id).sort());
  const table = page.locator('.data-table-wrapper').filter({ has: page.getByRole('heading', { name: 'Einzelabrechnungen pro Einheit', exact: true }) });
  await expect(table.locator('tbody tr')).toHaveCount(statements.length);
  await checkMobileWidth(page, testInfo, 'billing-draft-mobile');
});

test('bank allocation and reversal retain receipts and release the bank budget', async ({ page }, testInfo) => {
  const headers = await login(page);
  const charges = await api(page, '/rent-charges', headers);
  const charge = charges.find(item => item.status === 'partial');
  const contract = await api(page, `/contracts/${charge.contract_id}`, headers);
  const property = await api(page, `/properties/${contract.property_id}`, headers);
  const accounts = await api(page, '/accounts', headers);
  const account = accounts.find(item => item.portfolio_id === property.portfolio_id);
  expect(account).toBeTruthy();
  const note = `Bank browser ${randomUUID()}`;
  const amount = 7.89;
  const beforePaid = Number(charge.amount_paid);
  const booking = await api(page, '/bookings', headers, {
    account_id: account.id, property_id: contract.property_id, tenant_id: contract.tenant_id,
    unit_id: contract.unit_id, booking_date: '2026-09-20', amount, payment_text: note,
  });
  await page.goto('/rent-overview');
  const row = page.getByRole('row').filter({ hasText: contract.contract_number }).filter({ hasText: charge.month });
  await row.getByRole('button', { name: 'Bankbuchung zuordnen', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Bankbuchung', { exact: false }).selectOption(booking.id);
  await expect(dialog.getByLabel('Zahlungsbetrag (€)', { exact: false })).toHaveValue(String(amount));
  await expect(dialog.getByLabel('Zahlungsdatum', { exact: false })).toHaveValue(booking.booking_date);
  await dialog.getByLabel('Bemerkung', { exact: true }).fill(note);
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(row.locator('td').nth(5)).toHaveText(money(beforePaid + amount));
  const receipts = await api(page, `/rent-charges/${charge.id}/payments`, headers);
  const receipt = receipts.find(item => item.booking_id === booking.id);
  expect(receipt?.note).toBe(note);
  expect(Number((await api(page, `/bookings/${booking.id}`, headers)).allocated_amount)).toBeCloseTo(amount, 2);
  await row.getByRole('button', { name: 'Zahlungshistorie', exact: true }).click();
  const history = page.getByRole('region', { name: 'Zahlungshistorie', exact: true });
  const receiptRow = history.getByRole('row').filter({ hasText: note });
  await receiptRow.getByRole('button', { name: 'Stornieren', exact: true }).click();
  await dialog.getByLabel('Begründung', { exact: false }).fill('Buchung falsch zugeordnet');
  await dialog.getByLabel('Stornodatum', { exact: false }).fill('2026-09-21');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(receiptRow).toContainText('Storniert');
  await expect(receiptRow).toContainText('Buchung falsch zugeordnet');
  await expect(receiptRow.getByRole('button', { name: 'Stornieren', exact: true })).toHaveCount(0);
  await expect(row.locator('td').nth(5)).toHaveText(money(beforePaid));
  expect(Number((await api(page, `/bookings/${booking.id}`, headers)).allocated_amount)).toBe(0);
  const retained = await api(page, `/rent-charges/${charge.id}/payments`, headers);
  expect(retained.find(item => item.id === receipt.id)?.reversal.reason).toBe('Buchung falsch zugeordnet');
  await page.reload();
  await expect(row.locator('td').nth(5)).toHaveText(money(beforePaid));
  await row.getByRole('button', { name: 'Zahlungshistorie', exact: true }).click();
  await expect(history.getByRole('row').filter({ hasText: note })).toContainText('Storniert');
  await checkMobileWidth(page, testInfo, 'bank-reversal-mobile');
});
