import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('unit workspace: real exact context, independent pages, errors and mobile layout', async ({ page }, testInfo) => {
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
  const portfolio = await create('/portfolios', { name: `Einheitenbestand ${suffix}` });
  const property = await create('/properties', { portfolio_id: portfolio.id, name: `Lindenhof ${suffix}`, property_type: 'residential', address_line: 'Lindenstraße 18', postal_code: '80336', city: 'München' });
  const unit = await create('/units', { property_id: property.id, label: `Wohnung am Garten ${suffix}`, unit_type: 'apartment', cold_rent: 1234.56, service_charge_advance: 0, heating_advance: null, area_sqm: 72, rooms: 3, floor: 'EG' });
  const tenant = await create('/tenants', { full_name: `Testmieter ${suffix}` });
  const common = { property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2020-01-01', status: 'draft' };
  for (let index = 0; index < 26; index += 1) {
    await create('/contracts', { ...common, contract_number: `Entwurf ${suffix}-${index}` });
  }
  const activeNumber = `Aktueller Vertrag ${suffix}`;
  await create('/contracts', { ...common, contract_number: activeNumber, status: 'active', start_date: '2026-01-01', deposit_amount: 0 });
  await create('/insurances', { property_id: property.id, unit_id: unit.id, insurance_type: 'contents', provider: `Versicherung ${suffix}` });
  const workspacePath = `/api/v1/units/${unit.id}/workspace`;
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/v1/')) requests.push(url.pathname);
  });
  await page.goto(`/units/${unit.id}`);
  await expect(page.getByRole('heading', { name: unit.label, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: property.name, exact: true })).toHaveAttribute('href', `/properties/${property.id}`);
  const amount = name => page.getByText(name, { exact: true }).locator('..').locator('dd');
  await expect(amount('Kaltmiete')).toHaveText('1.234,56 €');
  await expect(amount('Nebenkostenvorauszahlung')).toHaveText('0,00 €');
  await expect(amount('Heizkostenvorauszahlung')).toHaveText('—');
  await expect(amount('Art')).toHaveText('Wohnung');
  await expect(page.getByText('Status der Einheit:', { exact: false })).toContainText('Leer');
  const current = page.getByRole('region', { name: 'Aktive Mietverträge', exact: true });
  const history = page.getByRole('region', { name: 'Vertragshistorie', exact: true });
  await expect(current).toContainText(tenant.full_name);
  await expect(history.getByRole('article')).toHaveCount(25);
  await history.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(history.getByRole('article')).toHaveCount(2);
  await expect(current.getByRole('heading', { name: activeNumber, exact: true })).toBeVisible();
  await history.getByRole('button', { name: 'Vorherige Seite', exact: true }).click();
  await expect(history.getByRole('article')).toHaveCount(25);
  expect(requests).toContain(workspacePath);
  expect(requests.filter(path => ['/api/v1/contracts', '/api/v1/tenants', '/api/v1/insurances'].includes(path))).toEqual([]);

  // A later server failure is a recoverable error, never an empty tenancy.
  await page.route(`**${workspacePath}?*`, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Vorübergehend nicht erreichbar' }) }));
  await page.getByRole('button', { name: 'Aktualisieren', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Vorübergehend nicht erreichbar');
  await expect(page.getByText(tenant.full_name, { exact: true })).toHaveCount(0);
  await page.unroute(`**${workspacePath}?*`);
  await page.getByRole('button', { name: 'Erneut laden', exact: true }).click();
  await expect(current).toContainText(tenant.full_name);

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`unit-workspace-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`unit-workspace-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});
