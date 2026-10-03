import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const passphrase = 'Role Browser Passphrase 2026';
const owner = { username: 'demo', password: 'Demo1234' };
const unique = prefix => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
async function login(page, account) {
  await page.goto('/login');
  await page.evaluate(() => { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.setItem('locale', 'de-DE'); });
  await page.reload();
  await page.getByLabel('Benutzername', { exact: true }).fill(account.username);
  await page.getByLabel('Passwort', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
}
async function headers(page) { return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }; }
async function get(page, path) {
  const response = await page.request.get(`/api/v1${path}`, { headers: await headers(page) });
  expect(response.status(), await response.text()).toBe(200); return response.json();
}
async function fixtureAccount(page, role) {
  await login(page, owner);
  const properties = await get(page, '/properties');
  const property = properties[0];
  expect(property?.portfolio_id).toBeTruthy();
  const hiddenProperty = properties.find(row => row.portfolio_id !== property.portfolio_id);
  expect(hiddenProperty, 'The isolated demo has a second portfolio to test the access boundary').toBeDefined();
  const username = unique(role);
  const response = await page.request.post('/api/v1/auth/users', { headers: await headers(page), data: {
    username, email: `${username}@example.com`, full_name: username, role, password: passphrase,
    portfolio_access: 'selected', portfolio_ids: [property.portfolio_id],
  } });
  expect(response.status(), await response.text()).toBe(201);
  const result = await response.json();
  expect(result).toMatchObject({ portfolio_access: 'selected', portfolio_ids: [property.portfolio_id] });
  if (role === 'techniker') {
    const period = await page.request.post('/api/v1/billing/periods', { headers: await headers(page), data: {
      property_id: property.id, label: unique('Role-readable period'), start_date: '2047-05-01', end_date: '2047-05-31', status: 'draft',
    } });
    expect(period.status(), await period.text()).toBe(201);
    result.testPeriodLabel = (await period.json()).label;
  }
  await login(page, { username, password: passphrase });
  expect(await get(page, '/auth/me')).toMatchObject({ id: result.id, role, portfolio_access: 'selected', portfolio_ids: [property.portfolio_id] });
  expect((await get(page, '/portfolios')).map(row => row.id)).toEqual([property.portfolio_id]);
  const denied = await page.request.get(`/api/v1/properties/${hiddenProperty.id}`, { headers: await headers(page) });
  expect(denied.status(), 'An explicit fixture grant must not expose another portfolio').toBe(404);
  return result;
}
async function loaded(page) {
  await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
  await expect(page.locator('.shared-data-table, .inventory-results').first()).toBeVisible();
}
async function noCreate(page, path) {
  await page.goto(path); await loaded(page);
  await expect(page.getByRole('button', { name: /(^Neu$|anlegen$|bearbeiten$|löschen$)/i })).toHaveCount(0);
}
async function propertiesReadOnly(page) {
  await page.goto('/properties');
  await expect(page.getByRole('heading', { name: 'Immobilien', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Immobilie anlegen', exact: true })).toHaveCount(0);
  await expect(page.locator('.property-card-actions')).toHaveCount(0);
}

test('accountant: actual finance creation and monthly preview, with portfolio and operations controls hidden', async ({ page }) => {
  test.setTimeout(120_000);
  const account = await fixtureAccount(page, 'buchhaltung');
  expect(account.write_permissions).toEqual(['billing', 'communication', 'documents', 'finance']);
  await propertiesReadOnly(page);
  await noCreate(page, '/maintenance');
  await noCreate(page, '/meters');
  await page.goto('/accounts'); await loaded(page);
  await page.getByRole('button', { name: 'Neu', exact: true }).click();
  const dialog = page.getByRole('dialog'); const name = unique('Buchhaltung Mietkonto');
  const portfolios = await get(page, '/portfolios'); expect(portfolios.length).toBeGreaterThan(0);
  await dialog.getByLabel(/^Portfolio/).selectOption(portfolios[0].id);
  await dialog.getByLabel(/^Kontoname/).fill(name);
  await dialog.getByLabel(/^Kontotyp/).selectOption('Mietkonto');
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/accounts' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const response = await saved; expect(response.status(), await response.text()).toBe(201); const created = await response.json();
  expect(await get(page, `/accounts/${created.id}`)).toMatchObject({ name, account_type: 'Mietkonto' });
  await page.reload(); await loaded(page); await page.locator('.shared-table-search input').fill(name);
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(1);
  await page.goto('/rent-charges'); await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  const generation = page.getByRole('dialog');
  const previewed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rent-charges/preview' && response.request().method() === 'POST');
  await generation.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  expect((await previewed).status()).toBe(200);
  await expect(generation.getByRole('button', { name: 'Sollstellungen buchen', exact: true })).toBeVisible();
  await generation.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await page.goto('/documents'); await loaded(page); await expect(page.locator('input[type="file"]')).toHaveCount(1);
});

test('technician: actual maintenance creation persists, finance and billing commands stay hidden', async ({ page }) => {
  test.setTimeout(120_000);
  const account = await fixtureAccount(page, 'techniker');
  expect(account.write_permissions).toEqual(['communication', 'documents', 'operations']);
  await propertiesReadOnly(page); await noCreate(page, '/accounts');
  await page.goto('/rent-charges'); await loaded(page);
  await expect(page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Neu', exact: true })).toHaveCount(0);
  await page.goto('/rent-overview'); await loaded(page);
  await expect(page.getByRole('button', { name: 'Zahlung erfassen', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Bankbuchung zuordnen', exact: true })).toHaveCount(0);
  await noCreate(page, '/statements');
  const row = page.getByRole('row').filter({ hasText: '2047-05-01' });
  await expect(row).toHaveCount(1); await row.click();
  await expect(page.locator('.detail-header')).toBeVisible();
  await expect(page.getByRole('heading', { name: account.testPeriodLabel, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Abrechnungen erstellen|Finalisieren|Korrektur starten|Forderungen.*buchen/ })).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await page.goto('/maintenance'); await loaded(page); await page.getByRole('button', { name: 'Wartungsfall anlegen', exact: true }).click();
  const dialog = page.getByRole('dialog'); const name = unique('Technik Reparatur');
  const properties = await get(page, '/properties'); expect(properties.length).toBeGreaterThan(0);
  await dialog.getByRole('button', { name: properties[0].name, exact: true }).click();
  await dialog.getByLabel(/^Titel/).fill(name);
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/maintenance' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const response = await saved; expect(response.status(), await response.text()).toBe(201); const created = await response.json();
  expect(await get(page, `/maintenance/${created.id}`)).toMatchObject({ title: name, property_id: properties[0].id });
  await page.reload(); await loaded(page); await page.getByLabel('Wartungsfälle durchsuchen', { exact: true }).fill(name);
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(1);
  await page.goto('/meters'); await loaded(page); await expect(page.getByRole('button', { name: 'Neu', exact: true })).toBeVisible();
  await page.goto('/documents'); await loaded(page); await expect(page.locator('input[type="file"]')).toHaveCount(1);
});

test('readonly: all business mutations hidden, own persisted preferences and account security still available', async ({ page }) => {
  test.setTimeout(120_000);
  const account = await fixtureAccount(page, 'readonly'); expect(account.write_permissions).toEqual([]);
  const forbidden = [];
  page.on('response', response => { if ([401, 403].includes(response.status())) forbidden.push(new URL(response.url()).pathname); });
  await propertiesReadOnly(page);
  for (const path of ['/accounts', '/maintenance', '/meters', '/rent-charges', '/statements', '/documents', '/contacts']) await noCreate(page, path);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await page.goto('/rent-overview'); await loaded(page);
  await expect(page.getByRole('button', { name: 'Zahlung erfassen', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Bankbuchung zuordnen', exact: true })).toHaveCount(0);
  await page.goto('/settings');
  await expect(page.getByRole('button', { name: 'Benutzer', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Entwicklung', exact: true })).toHaveCount(0);
  const authenticator = page.getByRole('button', { name: 'Authenticator einrichten', exact: true });
  await expect(authenticator).toBeVisible();
  const enrolled = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/2fa/setup' && response.request().method() === 'POST');
  await authenticator.click(); expect((await enrolled).status()).toBe(200);
  const changed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/users/me/preferences' && response.request().method() === 'PUT');
  await page.getByRole('button', { name: 'Dunkel', exact: true }).click();
  expect((await changed).status()).toBe(200); expect(await get(page, '/auth/users/me/preferences')).toMatchObject({ theme: 'dark' });
  await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: 'System', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Backup erstellen', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'JSON-Export', exact: true })).toHaveCount(0);
  await page.keyboard.press('Control+Shift+D'); await expect(page.locator('.dev-mode-overlay')).toHaveCount(0);
  expect(forbidden, 'Hidden or own-account controls must not accidentally call unauthorized API routes').toEqual([]);
});
