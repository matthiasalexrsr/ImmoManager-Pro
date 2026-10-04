import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('units: real full filter/export, bounded reference, failed form retry, and narrow screens', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const create = async (path, data) => {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const suffix = randomUUID().slice(0, 8);
  const portfolio = await create('/portfolios', { name: `Bestand ${suffix}` });
  let property;
  for (let index = 0; index < 102; index += 1) {
    property = await create('/properties', { portfolio_id: portfolio.id, name: `Haus ${suffix}-${index}`, property_type: 'residential' });
  }
  for (let index = 0; index < 27; index += 1) {
    await create('/units', { property_id: property.id, label: `Bestandswohnung ${suffix}-${String(index).padStart(2, '0')}`,
      unit_type: 'apartment', cold_rent: index ? 700 : 0, service_charge_advance: 0, heating_advance: null, status: index ? 'occupied' : 'vacant' });
  }
  const forbidden = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (['/api/v1/units', '/api/v1/properties', '/api/v1/contracts', '/api/v1/tenants'].includes(url.pathname) && request.method() === 'GET') forbidden.push(url.pathname);
  });
  await page.goto('/units');
  await page.getByRole('searchbox', { name: 'Einheiten durchsuchen' }).fill(`Bestandswohnung ${suffix}`);
  const table = page.getByRole('table');
  await expect(table.locator('tbody tr')).toHaveCount(25);
  await expect(page.getByRole('region', { name: 'Kennzahlen der gefilterten Einheiten' })).toContainText('27');
  await page.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(2);
  const downloadWait = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Alle gefilterten Einheiten exportieren' }).click();
  const download = await downloadWait;
  expect(await download.failure()).toBeNull();
  const csv = await readFile(await download.path(), 'utf8');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(28);
  expect(csv).toContain(`Bestandswohnung ${suffix}-00`);
  expect(csv).toContain(`Bestandswohnung ${suffix}-26`);

  await page.getByRole('button', { name: 'Einheit anlegen', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByRole('searchbox', { name: 'Immobilie suchen' }).fill(property.name);
  await dialog.getByRole('button', { name: property.name, exact: true }).click();
  await dialog.getByLabel('Bezeichnung', { exact: false }).fill(`Neue Wohnung ${suffix}`);
  await dialog.getByLabel('Art', { exact: false }).selectOption('apartment');
  await dialog.getByLabel('Kaltmiete (€)', { exact: true }).fill('0');
  await page.route('**/api/v1/units', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Speichern vorübergehend nicht möglich' }) }) : route.continue());
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert').filter({ hasText: 'Speichern vorübergehend nicht möglich' })).toBeVisible();
  await expect(dialog.getByLabel('Bezeichnung', { exact: false })).toHaveValue(`Neue Wohnung ${suffix}`);
  await expect(dialog).toContainText(`Ausgewählt: ${property.name}`);
  await page.unroute('**/api/v1/units');
  const proof = await page.request.get(`/api/v1/units/inventory/page?${new URLSearchParams({ search: `Neue Wohnung ${suffix}` })}`, { headers });
  expect(proof.ok()).toBeTruthy(); expect((await proof.json()).items).toHaveLength(0);
  await dialog.getByRole('button', { name: 'Nach Bestandsprüfung weiterbearbeiten', exact: true }).click();
  const createdWait = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/units' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await createdWait).status()).toBe(201);
  await expect(dialog).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Einheiten durchsuchen' }).fill(`Neue Wohnung ${suffix}`);
  await expect(page.getByRole('link', { name: `Neue Wohnung ${suffix}` })).toBeVisible();
  expect(forbidden).toEqual([]);

  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`unit-inventory-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`unit-inventory-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});
