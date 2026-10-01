import { createHmac } from 'node:crypto';
import { test, expect } from '@playwright/test';

// The second workflow deliberately uses the owner created by the first test in
// the same empty, private SQL installation. A failed setup must stop this chain.
test.describe.configure({ mode: 'serial' });

function authenticatorCode(secret, timestamp = Date.now()) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret.replaceAll('=', '')].map(char => alphabet.indexOf(char).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(timestamp / 30_000)));
  const digest = createHmac('sha1', key).update(counter).digest();
  return String((digest.readUInt32BE(digest[digest.length - 1] & 15) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

function incorrectCode(secret) {
  const now = Date.now();
  const accepted = new Set([-30_000, 0, 30_000].map(offset => authenticatorCode(secret, now + offset)));
  return ['000000', '111111', '222222', '333333'].find(code => !accepted.has(code));
}

test('empty installation: create owner, enroll authenticator, log in with code and disable', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
  const initialStatus = await page.request.get('/api/v1/auth/setup-status');
  expect(await initialStatus.json()).toMatchObject({ setup_required: true, setup_allowed: true, registration_open: false });
  const owner = { username: 'firstowner', email: 'firstowner@example.com', full_name: 'First Owner', password: 'Strong123' };
  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Eigentümerkonto erstellen', exact: true })).toBeVisible();
  await page.getByLabel('Benutzername', { exact: true }).fill(owner.username);
  await page.getByLabel('E-Mail-Adresse', { exact: true }).fill(owner.email);
  await page.getByLabel('Vollständiger Name', { exact: true }).fill(owner.full_name);
  await page.getByLabel('Passwort', { exact: true }).fill('weakpassword123');
  await page.getByRole('button', { name: 'Eigentümerkonto erstellen', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('Benutzername', { exact: true })).toHaveValue(owner.username);
  await page.getByLabel('Passwort', { exact: true }).fill(owner.password);
  const created = page.waitForResponse(response => response.url().endsWith('/auth/setup') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Eigentümerkonto erstellen', exact: true }).click();
  const creation = await created;
  expect(creation.status()).toBe(201);
  expect(await creation.json()).toMatchObject({ username: owner.username, role: 'eigentuemer' });
  await expect(page).toHaveURL(/\/$/);
  expect((await page.request.post('/api/v1/auth/setup', { data: owner })).status()).toBe(409);
  expect((await page.request.post('/api/v1/auth/register', { data: owner })).status()).toBe(403);

  await page.goto('/settings');
  const security = page.getByRole('region', { name: 'Zwei-Faktor-Authentifizierung', exact: true });
  await security.getByRole('button', { name: 'Authenticator einrichten', exact: true }).click();
  const secret = await security.getByLabel('Einrichtungsschlüssel', { exact: true }).inputValue();
  expect(secret).toMatch(/^[A-Z2-7]+=*$/);
  await expect(security.getByLabel('Authenticator-URI', { exact: true })).toHaveValue(/^otpauth:\/\/totp\//);
  const code = security.getByLabel('Authenticator-Code (6 Ziffern)', { exact: true });
  await code.fill(incorrectCode(secret));
  await security.getByRole('button', { name: 'Code bestätigen und aktivieren', exact: true }).click();
  await expect(security.getByRole('alert')).toHaveText('Ungültiger TOTP-Code');
  await expect(security.getByLabel('Einrichtungsschlüssel', { exact: true })).toHaveValue(secret);
  await code.fill(authenticatorCode(secret));
  await security.getByRole('button', { name: 'Code bestätigen und aktivieren', exact: true }).click();
  await expect(security.getByText('Zwei-Faktor-Authentifizierung wurde aktiviert.', { exact: true })).toBeVisible();
  await expect(security.getByLabel('Einrichtungsschlüssel', { exact: true })).not.toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  const screenshot = testInfo.outputPath('two-factor-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
  await testInfo.attach('two-factor-mobile', { path: screenshot, contentType: 'image/png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.evaluate(() => localStorage.clear());
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(owner.username);
  await page.getByLabel('Passwort', { exact: true }).fill(owner.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  const loginCode = page.getByLabel('Authenticator-Code (6 Ziffern)', { exact: true });
  await expect(loginCode).toBeVisible();
  await loginCode.fill(incorrectCode(secret));
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Ungültiger Zwei-Faktor-Code');
  await loginCode.fill(authenticatorCode(secret));
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto('/settings');
  await code.fill(incorrectCode(secret));
  await security.getByRole('button', { name: 'Mit Code deaktivieren', exact: true }).click();
  await expect(security.getByRole('alert')).toHaveText('Ungültiger TOTP-Code');
  await expect(security.getByRole('button', { name: 'Mit Code deaktivieren', exact: true })).toBeVisible();
  await code.fill(authenticatorCode(secret));
  await security.getByRole('button', { name: 'Mit Code deaktivieren', exact: true }).click();
  await expect(security.getByText('Zwei-Faktor-Authentifizierung wurde deaktiviert.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(security.getByText('Zwei-Faktor-Authentifizierung ist deaktiviert.', { exact: true })).toBeVisible();
  expect(errors, 'No uncaught browser errors').toEqual([]);
});

async function requestJson(page, headers, path, data, status = data === undefined ? 200 : 201) {
  const response = data === undefined
    ? await page.request.get(`/api/v1${path}`, { headers })
    : await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return response.json();
}

const money = amount => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);

async function bookedAccount(page, headers, contract, asOf, paid) {
  const account = await requestJson(page, headers, `/contracts/${contract.id}/settlement?as_of=${asOf}`);
  expect(account.source).toBe('booked_rent_charges');
  expect(account.summary).toMatchObject({ total_receivables: 1, total_expected: 750, total_paid: paid, total_outstanding: 750 - paid });
  expect(account.balance).toMatchObject({ expected_total: 750, paid_total: paid, outstanding_total: 750 - paid, overpaid_total: 0 });
  expect(account.settlement_lines).toHaveLength(1);
  expect(account.settlement_lines[0]).toMatchObject({ period_start: '2026-09-01', due_date: '2026-09-03', total_amount: 750, paid_amount: paid, outstanding_amount: 750 - paid });
  return account;
}

async function currentOpenItems(page, headers, charge, outstanding) {
  const report = await requestJson(page, headers, '/rent-charges/open-items');
  expect(report.source).toBe('monthly_rent_and_other_receivables');
  expect(report.total_outstanding).toBe(outstanding);
  if (outstanding > 0) {
    expect(report.items).toHaveLength(1);
    expect(report.items[0]).toMatchObject({ entity_type: 'rent_charge', entity_id: charge.id, month: '2026-09', due_date: '2026-09-03', amount_due: 750, amount_paid: 750 - outstanding, outstanding_amount: outstanding });
  } else {
    expect(report.items).toEqual([]);
  }
  const summary = await requestJson(page, headers, '/reports/summary');
  expect(summary.totals).toMatchObject({ properties: 1, units: 1, contracts: 1 });
  expect(summary.finance).toMatchObject({ openReceivables: outstanding, overdueReceivables: outstanding, openRentCharges: outstanding, openOtherReceivables: 0 });
  const aging = await requestJson(page, headers, '/reports/receivables-aging');
  expect(aging.openTotal).toBe(outstanding);
  expect(Object.values(aging.buckets).reduce((sum, value) => sum + value, 0)).toBe(outstanding);
}

async function recordManualPayment(page, row, charge, amount, date, note) {
  await row.getByRole('button', { name: 'Zahlung erfassen', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Zahlungsbetrag (€)', { exact: false }).fill(String(amount));
  await dialog.getByLabel('Zahlungsdatum', { exact: false }).fill(date);
  await dialog.getByLabel('Bemerkung', { exact: true }).fill(note);
  const saved = page.waitForResponse(response => response.url().endsWith(`/rent-charges/${charge.id}/payments`) && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const response = await saved;
  expect(response.status()).toBe(201);
  const receipt = await response.json();
  expect(Number(receipt.amount)).toBe(amount);
  expect(receipt).toMatchObject({ payment_date: date, note, booking_id: null, reversal: null });
  expect(receipt.idempotency_key).toBeTruthy();
  await expect(dialog).not.toBeVisible();
  return receipt;
}

test('first owner: monthly rent, manual and bank payments, dated reversal and booked account agree', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
  expect(await (await page.request.get('/api/v1/auth/setup-status')).json()).toMatchObject({ setup_required: false, registration_open: false });
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('firstowner');
  await page.getByLabel('Passwort', { exact: true }).fill('Strong123');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  // No demo data may enter this first-install acceptance path.
  for (const path of ['/portfolios', '/properties', '/units', '/tenants', '/contracts', '/rent-charges', '/receivables', '/bookings']) {
    expect(await requestJson(page, headers, path), `${path} must start empty`).toEqual([]);
  }
  const portfolio = await requestJson(page, headers, '/portfolios', { name: 'Browser First Portfolio', owner_name: 'First Owner' });
  const property = await requestJson(page, headers, '/properties', { portfolio_id: portfolio.id, name: 'Browser First House', property_type: 'residential', city: 'Berlin', address_line: 'Browserstraße 1' });
  const unit = await requestJson(page, headers, '/units', { property_id: property.id, label: 'Browser Apartment 1', unit_type: 'apartment', area_sqm: 60, cold_rent: 600, service_charge_advance: 100, heating_advance: 50 });
  const tenant = await requestJson(page, headers, '/tenants', { full_name: 'Browser First Tenant', email: 'browser-tenant@example.com' });
  const contract = await requestJson(page, headers, '/contracts', { contract_number: 'BROWSER-2026-001', property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-09-01', status: 'active' });
  const bankAccount = await requestJson(page, headers, '/accounts', { portfolio_id: portfolio.id, name: 'Browser Bank Account', account_type: 'checking' });
  const beforeGeneration = await requestJson(page, headers, `/contracts/${contract.id}/settlement?as_of=2026-09-30`);
  expect(beforeGeneration.balance).toMatchObject({ expected_total: 0, paid_total: 0, outstanding_total: 0 });
  expect(beforeGeneration.ungenerated_preview.total_amount).toBe(750);
  expect(beforeGeneration.settlement_lines).toEqual([]);
  expect((await requestJson(page, headers, `/contracts/${contract.id}/dunning-campaign?as_of=2026-09-30`, {}, 200)).total_cases).toBe(0);
  await currentOpenItems(page, headers, null, 0);

  await page.goto('/rent-charges');
  await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Ab Monat', { exact: false }).fill('2026-09');
  await dialog.getByLabel('Bis Monat', { exact: false }).fill('2026-09');
  await dialog.getByLabel('Verträge (optional)', { exact: false }).selectOption(contract.id);
  const inspected = page.waitForResponse(response => response.url().endsWith('/rent-charges/preview') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  const previewResponse = await inspected;
  expect(previewResponse.status()).toBe(200);
  const preview = await previewResponse.json();
  expect(preview).toMatchObject({ policy: 'full_month', total_amount: 750, existing: [], skipped_contracts: [] });
  expect(preview.candidates).toHaveLength(1);
  expect(preview.candidates[0]).toMatchObject({ contract_id: contract.id, month: '2026-09', cold_rent: 600, service_charge: 100, heating_charge: 50, total_amount: 750, due_date: '2026-09-03', partial_month: false });
  await expect(dialog).toContainText(money(750));
  const generated = page.waitForResponse(response => response.url().endsWith('/rent-charges/generate') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Sollstellungen buchen', exact: true }).click();
  const generationResponse = await generated;
  expect(generationResponse.status()).toBe(200);
  const generation = await generationResponse.json();
  expect(generation).toMatchObject({ created_count: 1, skipped_count: 0 });
  expect(generation.created).toHaveLength(1);
  const charge = generation.created[0];
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Erstellt: 1' })).toBeVisible();

  await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  await dialog.getByLabel('Ab Monat', { exact: false }).fill('2026-09');
  await dialog.getByLabel('Bis Monat', { exact: false }).fill('2026-09');
  await dialog.getByLabel('Verträge (optional)', { exact: false }).selectOption(contract.id);
  await dialog.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  await expect(dialog).toContainText('Bereits vorhanden: 1');
  await expect(dialog.getByRole('button', { name: 'Sollstellungen buchen', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  const replay = await requestJson(page, headers, '/rent-charges/generate', { start_month: '2026-09', end_month: '2026-09', contract_ids: [contract.id], preview_hash: preview.preview_hash }, 200);
  expect(replay).toMatchObject({ created_count: 0, skipped_count: 1, created: [] });
  expect((await requestJson(page, headers, '/rent-charges')).map(item => item.id)).toEqual([charge.id]);
  await bookedAccount(page, headers, contract, '2026-09-04', 0);
  await currentOpenItems(page, headers, charge, 750);

  await page.goto('/rent-overview');
  await page.getByLabel('Nur offene Posten', { exact: true }).uncheck();
  const row = page.getByRole('row').filter({ hasText: contract.contract_number }).filter({ hasText: '2026-09' });
  await expect(row).toHaveCount(1);
  const partial = await recordManualPayment(page, row, charge, 100, '2026-09-05', 'Browser partial receipt');
  await expect(row.locator('td').nth(5)).toHaveText(money(100));
  await expect(row.locator('td').nth(6)).toHaveText(money(650));
  await currentOpenItems(page, headers, charge, 650);
  await bookedAccount(page, headers, contract, '2026-09-05', 100);

  const booking = await requestJson(page, headers, '/bookings', { account_id: bankAccount.id, property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, booking_date: '2026-09-10', amount: 200, payment_text: 'Browser bank receipt' });
  // A bank transaction becomes rent paid only after an explicit allocation.
  await bookedAccount(page, headers, contract, '2026-09-10', 100);
  await row.getByRole('button', { name: 'Bankbuchung zuordnen', exact: true }).click();
  await dialog.getByLabel('Bankbuchung', { exact: false }).selectOption(booking.id);
  await expect(dialog.getByLabel('Zahlungsbetrag (€)', { exact: false })).toHaveValue('200');
  await expect(dialog.getByLabel('Zahlungsdatum', { exact: false })).toHaveValue('2026-09-10');
  await dialog.getByLabel('Bemerkung', { exact: true }).fill('Browser bank receipt');
  const allocated = page.waitForResponse(response => response.url().endsWith(`/rent-charges/${charge.id}/payments`) && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const allocationResponse = await allocated;
  expect(allocationResponse.status()).toBe(201);
  const linked = await allocationResponse.json();
  expect(Number(linked.amount)).toBe(200);
  expect(linked).toMatchObject({ booking_id: booking.id, payment_date: '2026-09-10', reversal: null });
  await expect(dialog).not.toBeVisible();
  await expect(row.locator('td').nth(5)).toHaveText(money(300));
  await expect(row.locator('td').nth(6)).toHaveText(money(450));
  expect((await requestJson(page, headers, `/bookings/${booking.id}`)).allocated_amount).toBe(200);
  await bookedAccount(page, headers, contract, '2026-09-11', 300);
  await currentOpenItems(page, headers, charge, 450);
  expect((await requestJson(page, headers, `/contracts/${contract.id}/dunning-campaign?as_of=2026-09-11`, {}, 200)).total_principal).toBe(450);

  await row.getByRole('button', { name: 'Zahlungshistorie', exact: true }).click();
  const history = page.getByRole('region', { name: 'Zahlungshistorie', exact: true });
  const bankRow = history.getByRole('row').filter({ hasText: 'Browser bank receipt' });
  await bankRow.getByRole('button', { name: 'Stornieren', exact: true }).click();
  await dialog.getByLabel('Begründung', { exact: false }).fill('Browser allocation assigned to wrong month');
  await dialog.getByLabel('Stornodatum', { exact: false }).fill('2026-09-12');
  const reversed = page.waitForResponse(response => response.url().endsWith(`/payments/${linked.id}/reversal`) && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const reversalResponse = await reversed;
  expect(reversalResponse.status()).toBe(201);
  const reversal = await reversalResponse.json();
  expect(Number(reversal.amount)).toBe(200);
  expect(reversal).toMatchObject({ payment_id: linked.id, reversal_date: '2026-09-12', reason: 'Browser allocation assigned to wrong month' });
  await expect(dialog).not.toBeVisible();
  await expect(bankRow).toContainText('Storniert');
  await expect(bankRow).toContainText(reversal.reason);
  await expect(bankRow.getByRole('button', { name: 'Stornieren', exact: true })).toHaveCount(0);
  await expect(row.locator('td').nth(5)).toHaveText(money(100));
  await expect(row.locator('td').nth(6)).toHaveText(money(650));
  expect((await requestJson(page, headers, `/bookings/${booking.id}`)).allocated_amount).toBe(0);
  const retained = await requestJson(page, headers, `/rent-charges/${charge.id}/payments`);
  expect(retained).toHaveLength(2);
  expect(retained.find(item => item.id === linked.id)?.reversal).toMatchObject({ id: reversal.id, reason: reversal.reason });
  await bookedAccount(page, headers, contract, '2026-09-04', 0);
  await bookedAccount(page, headers, contract, '2026-09-11', 300);
  await bookedAccount(page, headers, contract, '2026-09-12', 100);
  await currentOpenItems(page, headers, charge, 650);
  expect((await requestJson(page, headers, `/contracts/${contract.id}/dunning-campaign?as_of=2026-09-12`, {}, 200)).total_principal).toBe(650);

  const finalReceipt = await recordManualPayment(page, row, charge, 650, '2026-09-20', 'Browser final receipt');
  await expect(row.locator('td').nth(5)).toHaveText(money(750));
  await expect(row.locator('td').nth(6)).toHaveText(money(0));
  expect(await requestJson(page, headers, `/rent-charges/${charge.id}`)).toMatchObject({ amount_paid: 750, status: 'paid' });
  await currentOpenItems(page, headers, charge, 0);
  await bookedAccount(page, headers, contract, '2026-09-19', 100);
  await bookedAccount(page, headers, contract, '2026-09-20', 750);
  const october = await bookedAccount(page, headers, contract, '2026-10-15', 750);
  expect(october.ungenerated_preview.total_amount).toBe(750);
  expect(october.ungenerated_preview.candidates.map(item => item.month)).toEqual(['2026-10']);
  const campaign = await requestJson(page, headers, `/contracts/${contract.id}/dunning-campaign?as_of=2026-10-15`, {}, 200);
  expect(campaign).toMatchObject({ lines: [], total_cases: 0, total_principal: 0, total_claim: 0 });
  expect(await requestJson(page, headers, '/reports/cashflow')).toMatchObject({ incomeTotal: 200, expenseTotal: 0, netTotal: 200 });
  expect((await requestJson(page, headers, '/receivables'))).toEqual([]);
  const receipts = await requestJson(page, headers, `/rent-charges/${charge.id}/payments`);
  expect(receipts.map(item => item.id).sort()).toEqual([partial.id, linked.id, finalReceipt.id].sort());
  expect(receipts.filter(item => item.reversal)).toHaveLength(1);

  await page.reload();
  await page.getByLabel('Nur offene Posten', { exact: true }).uncheck();
  await expect(row.locator('td').nth(5)).toHaveText(money(750));
  await row.getByRole('button', { name: 'Zahlungshistorie', exact: true }).click();
  await expect(history.getByRole('row').filter({ hasText: 'Browser final receipt' })).toContainText(money(650));
  await expect(bankRow).toContainText(reversal.reason);
  await expect(history.locator('tbody tr')).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  const screenshot = testInfo.outputPath('first-owner-rent-history-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
  await testInfo.attach('first-owner-rent-history-mobile', { path: screenshot, contentType: 'image/png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  // Wide tables scroll within the card. Keep a second proof with the reversal
  // status and reason visible, rather than only the leftmost receipt columns.
  await history.locator('.table-scroll').evaluate(element => { element.scrollLeft = element.scrollWidth; });
  const reversalScreenshot = testInfo.outputPath('first-owner-reversal-mobile.png');
  await history.screenshot({ path: reversalScreenshot, animations: 'disabled' });
  await testInfo.attach('first-owner-reversal-mobile', { path: reversalScreenshot, contentType: 'image/png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(errors, 'No uncaught browser errors in the first-owner rental workflow').toEqual([]);
});
