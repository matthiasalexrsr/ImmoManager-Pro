import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('maintenance: complete filters/export, retained timed edit, bounded choices and narrow views', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const create = async (path, data) => {
    const reply = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(reply.status(), await reply.text()).toBe(201); return reply.json();
  };
  const suffix = randomUUID().slice(0, 8);
  const portfolio = await create('/portfolios', { name: `Wartungsbestand ${suffix}` });
  const property = await create('/properties', { portfolio_id: portfolio.id, name: `Werkhof ${suffix}`, property_type: 'residential' });
  const unit = await create('/units', { property_id: property.id, label: `Werkwohnung ${suffix}`, unit_type: 'apartment' });
  let item;
  for (let index = 0; index < 27; index += 1) item = await create('/maintenance', {
    title: `Wartungsfall ${suffix}-${String(index).padStart(2, '0')}`, property_id: property.id, unit_id: unit.id,
    description: 'Vollständiger unveränderter Bericht.', due_date: '2020-01-01', appointment_at: '2026-11-01T15:30:00',
    estimated_cost: 0, assignee: 'Anna', contractor: 'Musterbetrieb', category: 'Heizung', priority: 'high',
  });
  const globalReads = [];
  page.on('request', request => {
    if (request.method() === 'GET' && ['/api/v1/maintenance', '/api/v1/properties', '/api/v1/units'].includes(new URL(request.url()).pathname)) globalReads.push(request.url());
  });
  await page.goto('/maintenance');
  await page.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' }).fill(`Wartungsfall ${suffix}`);
  await page.getByLabel('Sortierung', { exact: true }).selectOption('title');
  const table = page.getByRole('table');
  await expect(table.locator('tbody tr')).toHaveCount(25);
  await expect(page.getByRole('region', { name: 'Kennzahlen der gefilterten Wartungsfälle' })).toContainText('27');
  await page.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(2);
  const downloadWait = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Alle gefilterten Wartungsfälle exportieren' }).click();
  const download = await downloadWait; expect(await download.failure()).toBeNull();
  const csv = await readFile(await download.path(), 'utf8');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(28);
  expect(csv).toContain(`Wartungsfall ${suffix}-00`); expect(csv).toContain(item.title);
  await page.getByRole('button', { name: `${item.title} bearbeiten` }).click();
  const dialog = page.getByRole('dialog', { name: 'Wartungsfall bearbeiten' });
  await expect(dialog.getByLabel('Beschreibung', { exact: true })).toHaveValue(item.description);
  await expect(dialog.getByLabel('Termin mit Uhrzeit')).toHaveValue('2026-11-01T15:30');
  const updatedTitle = `Geprüfter Wartungsfall ${suffix}`;
  await dialog.getByLabel('Titel', { exact: false }).fill(updatedTitle);
  await dialog.getByLabel('Termin mit Uhrzeit').fill('2026-11-02T16:45');
  const resource = `/api/v1/maintenance/${item.id}`;
  await page.route(`**${resource}`, route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Schreiben vorübergehend gesperrt' }) }) : route.continue());
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Schreiben vorübergehend gesperrt');
  await expect(dialog.getByLabel('Titel', { exact: false })).toHaveValue(updatedTitle);
  await expect(dialog.getByLabel('Termin mit Uhrzeit')).toHaveValue('2026-11-02T16:45');
  await page.unroute(`**${resource}`);
  const savedWait = page.waitForResponse(response => new URL(response.url()).pathname === resource && response.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await savedWait).status()).toBe(200); await expect(dialog).toHaveCount(0);
  const saved = await (await page.request.get(resource, { headers })).json();
  expect(saved.description).toBe(item.description); expect(saved.appointment_at).toContain('2026-11-02T16:45');
  expect(saved.estimated_cost).toBe(0);
  await page.getByRole('searchbox', { name: 'Wartungsfälle durchsuchen' }).fill(updatedTitle);
  await expect(table).toContainText(updatedTitle);
  await page.getByRole('button', { name: 'Wartungsfall anlegen', exact: true }).click();
  const form = page.getByRole('dialog', { name: 'Wartungsfall anlegen' });
  await form.getByLabel('Titel', { exact: false }).fill(`Neuer Auftrag ${suffix}`);
  await form.getByRole('searchbox', { name: 'Immobilie suchen' }).fill(property.name);
  await form.getByRole('button', { name: property.name, exact: true }).click();
  await form.getByRole('searchbox', { name: 'Einheit suchen' }).fill(unit.label);
  await form.getByRole('button', { name: unit.label, exact: true }).click();
  await form.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(form).toHaveCount(0);
  expect(globalReads).toEqual([]);
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`maintenance-inventory-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`maintenance-inventory-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});
