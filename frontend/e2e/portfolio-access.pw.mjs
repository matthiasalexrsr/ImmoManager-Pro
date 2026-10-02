import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const password = 'Portfolio Browser Passphrase 2026';
const unique = label => `${label}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function login(page, username, passphrase) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(passphrase);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
}
const headers = async page => ({ Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` });
async function create(page, path, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers: await headers(page), data });
  expect(response.status(), await response.text()).toBe(201); return response.json();
}
async function fixture(page, label) {
  const portfolio = await create(page, '/portfolios', { name: label });
  const property = await create(page, '/properties', { portfolio_id: portfolio.id, name: `${label} Objekt`, property_type: 'residential', city: 'Berlin' });
  const unit = await create(page, '/units', { property_id: property.id, label: `${label} Einheit`, unit_type: 'apartment' });
  const tenant = await create(page, '/tenants', { full_name: `${label} Mieter` });
  const contract = await create(page, '/contracts', { contract_number: unique(label), property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-01-01' });
  const charge = await create(page, '/rent-charges', { contract_id: contract.id, month: '2026-01', due_date: '2026-01-03', cold_rent: 100, service_charge: 10, heating_charge: 5, other_charges: 0 });
  const uploaded = await page.request.post('/api/v1/files/upload', { headers: await headers(page), multipart: { file: { name: `${label}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`PRIVATE ${label}`) } } });
  expect(uploaded.status(), await uploaded.text()).toBe(200);
  const file = await uploaded.json();
  const document = await create(page, '/documents', { title: `${label} Dokument`, property_id: property.id, file_url: file.file_url });
  return { portfolio, property, unit, tenant, contract, charge, document, file };
}
async function management(page) {
  await page.goto('/settings'); await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  const section = page.getByRole('region', { name: 'Benutzerverwaltung', exact: true });
  await expect(section.getByRole('table')).toBeVisible(); return section;
}

test('owner portfolio selection persists and a second logged-in session immediately loses replaced access', async ({ page, browser }, testInfo) => {
  test.setTimeout(150_000);
  await login(page, 'demo', 'Demo1234');
  const left = await fixture(page, unique('Team A'));
  const right = await fixture(page, unique('Team B'));
  const section = await management(page);
  await section.getByRole('button', { name: 'Benutzer anlegen', exact: true }).click();
  const dialog = page.getByRole('dialog'); const username = unique('portfolio-user'); const name = `Team ${username}`;
  await dialog.getByLabel(/^Benutzername/).fill(username);
  await dialog.getByLabel(/^Vollständiger Name/).fill(name);
  await dialog.getByLabel(/^E-Mail-Adresse/).fill(`${username}@example.test`);
  await dialog.getByLabel(/^Startpassphrase/).fill(password);
  await dialog.getByLabel(/^Rolle/).selectOption('verwalter');
  await expect(dialog.getByLabel(/^Portfoliozugriff/)).toHaveValue('selected');
  await dialog.getByLabel('Zugewiesene Portfolios', { exact: true }).selectOption([left.portfolio.id]);
  const created = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/users' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const creation = await created; expect(creation.status(), await creation.text()).toBe(201);
  const account = await creation.json();
  expect(account).toMatchObject({ portfolio_access: 'selected', portfolio_ids: [left.portfolio.id], portfolio_access_origin: 'owner_assignment' });
  await expect(dialog).not.toBeVisible();
  await page.reload(); await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  await expect(section.getByRole('row').filter({ hasText: username })).toContainText(left.portfolio.name);

  const context = await browser.newContext({ baseURL: process.env.IMMO_E2E_URL, locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  const member = await context.newPage(); const errors = []; member.on('pageerror', error => errors.push(error.message));
  try {
    await login(member, username, password);
    const originalToken = await member.evaluate(() => localStorage.getItem('access_token'));
    await member.goto('/properties');
    await expect(member.getByRole('heading', { name: left.property.name, exact: true })).toBeVisible();
    await expect(member.getByRole('heading', { name: right.property.name, exact: true })).toHaveCount(0);
    const scopedHeaders = { Authorization: `Bearer ${originalToken}` };
    expect((await member.request.get(`/api/v1/rent-charges/${right.charge.id}`, { headers: scopedHeaders })).status()).toBe(404);
    expect((await member.request.get(`/api/v1/billing/contracts/${right.contract.id}/credits`, { headers: scopedHeaders })).status()).toBe(404);
    expect((await member.request.get(right.file.file_url.startsWith('/') ? right.file.file_url : `/${right.file.file_url}`, { headers: scopedHeaders })).status()).toBe(404);
    const cross = await member.request.post('/api/v1/tasks', { headers: scopedHeaders, data: { title: 'Forbidden cross-reference', property_id: left.property.id, unit_id: right.unit.id } });
    expect([400, 403, 404, 422]).toContain(cross.status());
    const summary = await member.request.get('/api/v1/reports/summary', { headers: scopedHeaders });
    expect(summary.status()).toBe(200); expect((await summary.json()).totals.properties).toBe(1);
    await member.goto('/settings');
    await expect(member.getByRole('button', { name: 'Benutzer', exact: true })).toHaveCount(0);

    await section.getByRole('button', { name: `${name} bearbeiten`, exact: true }).click();
    const editor = page.getByRole('dialog');
    await expect(editor.getByLabel('Zugewiesene Portfolios', { exact: true })).toHaveValues([left.portfolio.id]);
    await editor.getByLabel('Zugewiesene Portfolios', { exact: true }).selectOption([right.portfolio.id]);
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/auth/users/${account.id}` && response.request().method() === 'PATCH');
    await editor.getByRole('button', { name: 'Speichern', exact: true }).click();
    const response = await saved; expect(response.status(), await response.text()).toBe(200);
    expect(response.request().postDataJSON()).toEqual({ portfolio_access: 'selected', portfolio_ids: [right.portfolio.id] });
    await expect(editor).not.toBeVisible();
    // Existing token, independent browser context, no logout or injected refresh.
    expect((await member.request.get(`/api/v1/properties/${left.property.id}`, { headers: scopedHeaders })).status()).toBe(404);
    expect((await member.request.get(`/api/v1/properties/${right.property.id}`, { headers: scopedHeaders })).status()).toBe(200);
    expect((await member.request.get(`/api/v1/billing/contracts/${right.contract.id}/credits`, { headers: scopedHeaders })).status()).toBe(200);
    const ownFile = await member.request.get(right.file.file_url.startsWith('/') ? right.file.file_url : `/${right.file.file_url}`, { headers: scopedHeaders });
    expect(ownFile.status()).toBe(200); expect(await ownFile.text()).toContain(right.portfolio.name);
    const prefs = await member.request.put('/api/v1/auth/users/me/preferences', { headers: scopedHeaders, data: { locale: 'de-DE', theme: 'light' } });
    expect(prefs.status()).toBe(200);
    await member.goto('/properties');
    await expect(member.getByRole('heading', { name: right.property.name, exact: true })).toBeVisible();
    await expect(member.getByRole('heading', { name: left.property.name, exact: true })).toHaveCount(0);
    expect(await member.evaluate(() => localStorage.getItem('access_token'))).toBe(originalToken);
    for (const width of [390, 320]) {
      await member.setViewportSize({ width, height: 844 });
      await expect.poll(() => member.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      const screenshot = testInfo.outputPath(`portfolio-scope-${width}.png`);
      await member.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
      await testInfo.attach(`portfolio-scope-${width}`, { path: screenshot, contentType: 'image/png' });
    }
    expect(errors).toEqual([]);
  } finally { await context.close(); }
});
