import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('property inventory: real creation, weighted occupancy, filters and persistent edit', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const api = async (path, data) => {
    const response = data === undefined
      ? await page.request.get(`/api/v1${path}`, { headers })
      : await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const all = async path => {
    const rows = [];
    for (let skip = 0; ; skip += 100) {
      const batch = await api(`${path}?skip=${skip}&limit=100&sort_by=id&sort_order=asc`);
      expect(Array.isArray(batch)).toBe(true);
      rows.push(...batch);
      if (batch.length < 100) return rows;
    }
  };
  const suffix = randomUUID().slice(0, 8);
  const portfolio = await api('/portfolios', { name: `Browserbestand ${suffix}` });
  const originalName = `Lindenhof ${suffix}`;
  const updatedName = `Lindenhof am Park ${suffix}`;

  await page.goto('/properties');
  await page.getByRole('button', { name: 'Immobilie anlegen', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/^Portfolio/).selectOption(portfolio.id);
  await dialog.getByLabel(/^Objektname/).fill(originalName);
  await dialog.getByLabel(/^Objektart/).selectOption('residential');
  await dialog.getByLabel('Straße und Hausnummer', { exact: true }).fill('Parkstraße 12');
  await dialog.getByLabel('PLZ', { exact: true }).fill('80336');
  await dialog.getByLabel('Ort', { exact: true }).fill('München');
  const createdResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/properties' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  const property = await created.json();
  const identity = page.getByRole('link', { name: originalName, exact: true });
  await expect(identity).toHaveAttribute('href', `/properties/${property.id}`);
  await expect(page.getByRole('article').filter({ has: identity })).toContainText('Parkstraße 12, 80336 München');

  // Unequal property sizes prove that occupancy uses units as its denominator.
  await api('/units', { property_id: property.id, label: `Freie Wohnung ${suffix}`, unit_type: 'apartment', status: 'vacant', area_sqm: 70, cold_rent: 900 });
  const largeProperty = await api('/properties', { portfolio_id: portfolio.id, name: `Stadthaus ${suffix}`, property_type: 'residential' });
  for (let index = 0; index < 9; index += 1) {
    await api('/units', { property_id: largeProperty.id, label: `Wohnung ${index + 1} ${suffix}`, unit_type: 'apartment', status: index ? 'occupied' : 'rented', area_sqm: 45, cold_rent: 650 });
  }
  const allProperties = await all('/properties');
  const propertyIds = new Set(allProperties.map(item => item.id));
  const allUnits = (await all('/units')).filter(unit => propertyIds.has(unit.property_id));
  const occupiedCount = allUnits.filter(unit => ['occupied', 'rented'].includes(unit.status)).length;
  await page.reload();
  const summary = page.getByRole('region', { name: 'Bestand im Überblick' });
  await expect(summary).toContainText(`${Math.round(occupiedCount / allUnits.length * 100)}%`);
  await expect(summary).toContainText(`${occupiedCount} von ${allUnits.length} Einheiten belegt`);

  await page.getByRole('combobox', { name: 'Portfolio', exact: true }).selectOption(portfolio.id);
  await expect(page.getByRole('article')).toHaveCount(2);
  await page.getByRole('button', { name: 'Mit freien Einheiten', exact: true }).click();
  await expect(page.getByRole('article')).toHaveCount(1);
  await page.getByRole('searchbox', { name: 'Immobilien durchsuchen' }).fill('Parkstraße');
  await expect(identity).toBeVisible();
  await page.getByRole('button', { name: 'Tabellenansicht' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('link', { name: new RegExp(originalName) })).toHaveAttribute('href', `/properties/${property.id}`);
  await page.getByRole('button', { name: 'Kartenansicht' }).click();
  await page.getByRole('button', { name: `${originalName} bearbeiten`, exact: true }).click();
  await dialog.getByLabel(/^Objektname/).fill(updatedName);
  const updatedResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/properties/${property.id}` && response.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await updatedResponse).status()).toBe(200);
  await expect(page.getByRole('link', { name: updatedName, exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('searchbox', { name: 'Immobilien durchsuchen' }).fill(updatedName);
  const updatedLink = page.getByRole('link', { name: updatedName, exact: true });
  await expect(updatedLink).toBeVisible();
  expect((await api(`/properties/${property.id}`)).name).toBe(updatedName);
  await updatedLink.click();
  await expect(page).toHaveURL(new RegExp(`/properties/${property.id}$`));
  await expect(page.getByRole('heading', { name: updatedName, level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: new RegExp(`Freie Wohnung ${suffix}`) })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  // The shared shell animates its desktop margin when the viewport becomes mobile.
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const screenshot = testInfo.outputPath('property-detail-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('property-detail-mobile', { path: screenshot, contentType: 'image/png' });
  expect(errors).toEqual([]);
});
