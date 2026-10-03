import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('documents: full metadata sources, retained edits, versions and narrow layouts', async ({ page }, testInfo) => {
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
  const portfolio = await create('/portfolios', { name: `Dokumentenbestand ${suffix}` });
  const property = await create('/properties', { portfolio_id: portfolio.id, name: `Aktenhaus ${suffix}`, property_type: 'residential' });
  const unit = await create('/units', { property_id: property.id, label: `Archivwohnung ${suffix}`, unit_type: 'apartment' });
  const upload = await page.request.post('/api/v1/files/upload', { headers, multipart: { file: { name: `Original-${suffix}.txt`, mimeType: 'text/plain', buffer: Buffer.from('Synthetic retained original.\n') } } });
  expect(upload.status(), await upload.text()).toBe(200);
  const source = await upload.json();
  let document;
  for (let index = 0; index < 27; index += 1) document = await create('/documents', {
    title: `Bestandsdokument ${suffix}-${String(index).padStart(2, '0')}`, property_id: property.id, unit_id: unit.id,
    file_url: source.file_url, document_type: 'Rechnung', description: 'Dieser vollständige Text muss beim Bearbeiten erhalten bleiben.', document_date: '2026-01-01',
  });
  const globalReads = [];
  page.on('request', request => {
    if (request.method() === 'GET' && ['/api/v1/documents', '/api/v1/properties', '/api/v1/units', '/api/v1/contracts'].includes(new URL(request.url()).pathname)) globalReads.push(request.url());
  });
  await page.goto('/documents');
  await page.getByRole('searchbox', { name: 'Dokumente durchsuchen' }).fill(`Bestandsdokument ${suffix}`);
  const table = page.getByRole('table');
  await expect(table.locator('tbody tr')).toHaveCount(25);
  await expect(page.getByRole('region', { name: 'Kennzahlen der gefilterten Dokumente' })).toContainText('27');
  await page.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(2);
  const downloadWait = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Alle gefilterten Dokumente exportieren' }).click();
  const download = await downloadWait;
  expect(await download.failure()).toBeNull();
  const csv = await readFile(await download.path(), 'utf8');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(28);
  expect(csv).toContain(`Bestandsdokument ${suffix}-00`); expect(csv).toContain(document.title);
  await page.getByRole('button', { name: `${document.title} bearbeiten` }).click();
  const dialog = page.getByRole('dialog', { name: 'Dokument bearbeiten' });
  await expect(dialog.getByLabel('Beschreibung', { exact: true })).toHaveValue(document.description);
  const updatedTitle = `Geprüftes Dokument ${suffix}`;
  await dialog.getByLabel('Titel', { exact: false }).fill(updatedTitle);
  const resource = `/api/v1/documents/${document.id}`;
  await page.route(`**${resource}`, route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Schreibvorgang vorübergehend gesperrt' }) }) : route.continue());
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Schreibvorgang vorübergehend gesperrt');
  await expect(dialog.getByLabel('Titel', { exact: false })).toHaveValue(updatedTitle);
  await page.unroute(`**${resource}`);
  const savedWait = page.waitForResponse(response => new URL(response.url()).pathname === resource && response.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await savedWait).status()).toBe(200);
  await expect(dialog).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Dokumente durchsuchen' }).fill(updatedTitle);
  await expect(page.getByRole('button', { name: updatedTitle, exact: true })).toBeVisible();
  await page.getByRole('button', { name: `${updatedTitle} Versionshistorie` }).click();
  const history = page.getByRole('dialog', { name: 'Dokumentversionen' });
  await expect(history).toBeVisible();
  await history.getByRole('button', { name: 'Schließen', exact: true }).click();
  expect(globalReads).toEqual([]);
  expect((await (await page.request.get(resource, { headers })).json()).description).toBe(document.description);

  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`document-inventory-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`document-inventory-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});
