import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
}
async function fixture(page, kind = 'invoice') {
  await login(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const api = async (path, data, method = 'post') => {
    const response = data === undefined ? await page.request.get(`/api/v1${path}`, { headers })
      : await page.request[method](`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const prefix = `Match ${randomUUID().slice(0, 8)}`;
  const portfolio = await api('/portfolios', { name: prefix });
  const property = await api('/properties', { portfolio_id: portfolio.id, name: prefix, property_type: 'residential' });
  const account = await api('/accounts', { portfolio_id: portfolio.id, name: prefix, account_type: 'bank' });
  let target, other;
  if (kind === 'invoice') {
    target = await api('/invoices', { property_id: property.id, supplier: prefix, invoice_number: prefix,
      invoice_date: '2026-09-01', gross_amount: 100.30, net_amount: 100.30, vat_rate: 0 });
  } else {
    const unit = await api('/units', { property_id: property.id, label: 'WE1', unit_type: 'apartment' });
    const tenant = await api('/tenants', { full_name: prefix });
    const contract = await api('/contracts', { contract_number: prefix, property_id: property.id, unit_id: unit.id,
      tenant_id: tenant.id, start_date: '2026-01-01' });
    target = await api('/rent-charges', { contract_id: contract.id, month: '2026-09', cold_rent: 100.30 });
    other = await api('/rent-charges', { contract_id: contract.id, month: '2026-10', cold_rent: 100.30 });
  }
  const booking = await api('/bookings', { account_id: account.id, booking_date: '2026-09-05', amount: kind === 'invoice' ? -100.30 : 100.30,
    payment_text: prefix, property_id: property.id });
  return { api, prefix, target, other, booking, account };
}
async function open(page, data, fromInvoice = false) {
  if (fromInvoice) {
    await page.goto('/invoices');
    const row = page.getByRole('row').filter({ hasText: data.prefix });
    await expect(row).toHaveCount(1);
    await row.getByRole('link', { name: 'Ausgehende Bankbuchung auswählen', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`invoice_id=${data.target.id}`));
  } else await page.goto(`/bookings?account_id=${data.account.id}`);
  await page.getByRole('button', { name: `Zuordnung prüfen ${data.prefix}`, exact: true }).click();
  const panel = page.getByRole('region', { name: 'Bankbuchung zuordnen', exact: true });
  if (!fromInvoice) {
    await panel.getByRole('searchbox', { name: 'Referenz, Name oder Kennung suchen', exact: true }).fill(data.prefix);
    await panel.getByRole('button', { name: 'Vorschläge suchen', exact: true }).click();
  }
  await expect(panel.getByRole('radio').first()).toBeVisible();
  return panel;
}
async function approve(page, panel, amount = '40,10') {
  await panel.getByLabel('Zuordnungsbetrag (€)', { exact: true }).fill(amount);
  await panel.getByRole('button', { name: 'Zuordnung verbindlich bestätigen', exact: true }).click();
  const confirmation = page.getByRole('alertdialog');
  await expect(confirmation).toContainText('dem ausgewählten offenen Posten zuordnen');
  const pending = page.waitForResponse(response => /\/bookings\/[^/]+\/matching$/.test(new URL(response.url()).pathname)
    && response.request().method() === 'POST');
  await confirmation.getByRole('button', { name: 'Bestätigen', exact: true }).click();
  return pending;
}

test('invoice allocation uses a deliberate real bank receipt, persists partial balance and reverses without a second cash movement', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const data = await fixture(page);
  const panel = await open(page, data, true);
  await expect(panel.getByRole('radio')).not.toBeChecked();
  expect(await data.api(`/invoices/${data.target.id}/payments`)).toEqual([]);
  await panel.getByRole('radio').check();
  await panel.getByLabel('Zuordnungsbetrag (€)', { exact: true }).fill('40,10');
  await panel.getByRole('button', { name: 'Zuordnung verbindlich bestätigen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Abbrechen', exact: true }).click();
  expect(await data.api(`/invoices/${data.target.id}/payments`)).toEqual([]);
  const response = await approve(page, panel);
  expect(response.status(), await response.text()).toBe(201);
  const receipt = await response.json();
  expect(receipt.amount).toBe('40.10'); expect(receipt.booking_id).toBe(data.booking.id);
  expect(receipt.payment_date).toBe('2026-09-05');
  await expect(panel.getByText(receipt.id, { exact: true }).first()).toBeVisible();
  const command = response.request().postDataJSON();
  const replay = await data.api(`/bookings/${data.booking.id}/matching`, command);
  expect(replay.id).toBe(receipt.id);
  expect(Number((await data.api(`/invoices/${data.target.id}`)).amount_paid)).toBe(40.10);
  expect(Number((await data.api(`/bookings/${data.booking.id}`)).allocated_amount)).toBe(40.10);
  expect(Number((await data.api(`/accounts/${data.account.id}`)).balance)).toBe(0);
  expect((await data.api(`/accounts/${data.account.id}/balance-summary`)).calculated_balance_cents).toBe('-10030');
  expect((await data.api(`/bookings/page?account_id=${data.account.id}&page_size=25`)).items).toHaveLength(1);

  await page.reload();
  await page.getByRole('button', { name: `Zuordnung prüfen ${data.prefix}`, exact: true }).click();
  await expect(panel.getByText(receipt.id, { exact: true })).toBeVisible();
  await expect(panel).toContainText('60,20 €');
  const history = panel.getByRole('region', { name: 'Zahlungsbelege und Stornos', exact: true });
  await history.getByRole('button', { name: 'Zahlungsbeleg stornieren', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Stornodatum', { exact: false }).fill('2026-09-06');
  await dialog.getByLabel('Begründung', { exact: false }).fill('Bewusste Korrektur der Bankzuordnung');
  await dialog.getByRole('button', { name: 'Zahlungsbeleg stornieren', exact: true }).click();
  const reversed = page.waitForResponse(response => /\/payments\/[^/]+\/reversal$/.test(new URL(response.url()).pathname));
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  const reversedResponse = await reversed;
  expect(reversedResponse.status(), await reversedResponse.text()).toBe(201);
  await expect(history).toContainText('Bewusste Korrektur der Bankzuordnung');
  expect(Number((await data.api(`/invoices/${data.target.id}`)).amount_paid)).toBe(0);
  expect(Number((await data.api(`/bookings/${data.booking.id}`)).allocated_amount)).toBe(0);
  expect(Number((await data.api(`/accounts/${data.account.id}`)).balance)).toBe(0);
  expect((await data.api(`/accounts/${data.account.id}/balance-summary`)).calculated_balance_cents).toBe('-10030');
  const retained = await data.api(`/invoices/${data.target.id}/payments?page_size=25`);
  expect(retained.items).toHaveLength(1); expect(retained.items[0].id).toBe(receipt.id);
  expect(retained.items[0].reversal.payment_id).toBe(receipt.id);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width > 400 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`bank-matching-${width}.png`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`Bankzuordnung ${width}px`, { path: screenshot, contentType: 'image/png' });
  }
  await page.goto('/invoices');
  const invoiceRow = page.getByRole('row').filter({ hasText: data.prefix });
  await expect(invoiceRow).toContainText('100,30 €');
  await invoiceRow.getByRole('button', { name: 'Zahlungsbelege und Stornos', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Zahlungsbelege und Stornos', exact: true })).toContainText('Bewusste Korrektur der Bankzuordnung');
});

test('ambiguous monthly obligations require manual selection and a changed bank source requires renewed review', async ({ page }) => {
  test.setTimeout(150_000);
  const data = await fixture(page, 'rent_charge');
  const panel = await open(page, data);
  await expect(panel).toContainText('Mehrere Posten passen gleich gut');
  await expect(panel.getByRole('radio')).toHaveCount(2);
  for (const radio of await panel.getByRole('radio').all()) await expect(radio).not.toBeChecked();
  await panel.getByRole('radio').first().check();
  await data.api(`/bookings/${data.booking.id}`, { payment_text: `${data.prefix} nach Prüfung geändert` }, 'patch');
  const failed = await approve(page, panel);
  expect(failed.status(), await failed.text()).toBe(409);
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Zuordnung verbindlich bestätigen', exact: true })).toHaveCount(0);
  expect(await data.api(`/rent-charges/${data.target.id}/payments`)).toEqual([]);
  expect(await data.api(`/rent-charges/${data.other.id}/payments`)).toEqual([]);
  await panel.getByRole('button', { name: 'Erneut prüfen', exact: true }).click();
  await expect(panel.getByText(`${data.prefix} nach Prüfung geändert`, { exact: true })).toBeVisible();
  await panel.getByRole('radio').first().check();
  const successful = await approve(page, panel, '10,01');
  expect(successful.status(), await successful.text()).toBe(201);
  const receipt = await successful.json();
  expect(receipt.entity_type).toBe('rent_charge'); expect(receipt.amount).toBe('10.01');
  expect([data.target.id, data.other.id]).toContain(receipt.entity_id);
  expect(Number((await data.api(`/rent-charges/${receipt.entity_id}`)).amount_paid)).toBe(10.01);
  expect(Number((await data.api(`/bookings/${data.booking.id}`)).allocated_amount)).toBe(10.01);
});

test('readonly can inspect genuine candidates and stored invoice receipts but cannot confirm or reverse', async ({ page }) => {
  test.setTimeout(120_000);
  const data = await fixture(page);
  const review = await data.api(`/bookings/${data.booking.id}/suggestions?kind=invoice&search=${data.target.id}`);
  const receipt = await data.api(`/bookings/${data.booking.id}/matching`, { review_token: review.items[0].review_token, amount: '1.01', idempotency_key: randomUUID() });
  const username = `readonly-${randomUUID().slice(0, 8)}`;
  await data.api('/auth/users', { username, email: `${username}@example.test`, full_name: 'Synthetic bank reader',
    password: 'BankReadOnly123!', role: 'readonly', portfolio_access: 'all', portfolio_ids: [] });
  await page.evaluate(() => { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); });
  await login(page, username, 'BankReadOnly123!');
  const panel = await open(page, data);
  await expect(panel.getByRole('radio')).toBeDisabled();
  await expect(panel.getByText(receipt.id, { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Zuordnung verbindlich bestätigen', exact: true })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: 'Zahlungsbeleg stornieren', exact: true })).toHaveCount(0);
  expect((await data.api(`/invoices/${data.target.id}/payments`))).toHaveLength(1);
});
