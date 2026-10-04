import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function workspace(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const request = async (path, data, method = data === undefined ? 'get' : 'post') => {
    const response = await page.request[method](`/api/v1${path}`, { headers, ...(data === undefined ? {} : { data }) });
    expect(response.ok(), await response.text()).toBeTruthy(); return response.json();
  };
  return { request, headers, suffix: randomUUID().slice(0, 8) };
}

async function edit(page, company) {
  await page.goto('/contacts');
  await page.getByRole('searchbox', { name: 'Kontakte durchsuchen' }).fill(company);
  await page.getByRole('button', { name: `${company} bearbeiten`, exact: true }).click();
  return page.getByRole('dialog', { name: 'Kontakt bearbeiten' });
}

test('contacts: complete CSV, retained private fields, encrypted draft reload and narrow views', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const { request, suffix } = await workspace(page);
  let contact;
  for (let index = 0; index < 27; index += 1) contact = await request('/contacts', {
    company_name: `Kontaktbestand ${suffix}-${String(index).padStart(2, '0')}`, contact_type: 'supplier', email: `test-${index}@example.test`,
    notes: 'Private retained note', country: 'AT', bic: 'SYNTHETIC', iban: 'SYNTHETIC-IBAN', tax_id: 'SYNTHETIC-TAX',
  });
  const globalReads = [];
  page.on('request', r => { if (r.method() === 'GET' && new URL(r.url()).pathname === '/api/v1/contacts') globalReads.push(r.url()); });
  await page.goto('/contacts');
  await page.getByRole('searchbox', { name: 'Kontakte durchsuchen' }).fill(`Kontaktbestand ${suffix}`);
  const table = page.getByRole('table');
  await expect(table.locator('tbody tr')).toHaveCount(25);
  await expect(page.getByRole('region', { name: 'Kennzahlen der gefilterten Kontakte' })).toContainText('27');
  await page.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(2);
  const downloadWait = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Alle gefilterten Kontakte exportieren' }).click();
  const download = await downloadWait; expect(await download.failure()).toBeNull();
  const csv = await readFile(await download.path(), 'utf8');
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(28);
  expect(csv).toContain(`Kontaktbestand ${suffix}-00`); expect(csv).toContain(contact.company_name);
  expect(csv).not.toContain('Private retained note'); expect(csv).not.toContain('SYNTHETIC-IBAN');
  await page.getByRole('button', { name: `${contact.company_name} bearbeiten` }).click();
  let dialog = page.getByRole('dialog', { name: 'Kontakt bearbeiten' });
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('BIC')).toHaveValue('SYNTHETIC');
  await expect(dialog.getByLabel('Land')).toHaveValue('AT');
  const changedName = `Geprüfter Kontakt ${suffix}`;
  await dialog.getByLabel('Firma', { exact: true }).fill(changedName);
  await expect(dialog.getByText('Persönlicher Entwurf gesichert', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await page.reload(); dialog = await edit(page, contact.company_name);
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel('Firma', { exact: true })).toHaveValue(changedName);
  const resource = `/api/v1/contacts/${contact.id}`;
  await page.route(`**${resource}`, route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Schreiben vorübergehend gesperrt' }) }) : route.continue());
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert').filter({ hasText: 'Schreiben vorübergehend gesperrt' })).toBeVisible();
  await expect(dialog.getByLabel('Firma', { exact: true })).toHaveValue(changedName);
  await page.unroute(`**${resource}`);
  expect((await request(`/contacts/${contact.id}`)).company_name).toBe(contact.company_name);
  await dialog.getByRole('button', { name: 'Nach Bestandsprüfung weiterbearbeiten', exact: true }).click();
  const savedWait = page.waitForResponse(response => new URL(response.url()).pathname === resource && response.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await savedWait).status()).toBe(200); await expect(dialog).toHaveCount(0);
  const saved = await request(`/contacts/${contact.id}`);
  expect(saved).toMatchObject({ company_name: changedName, notes: contact.notes, country: 'AT', bic: 'SYNTHETIC', iban: contact.iban, tax_id: contact.tax_id });
  await page.getByRole('searchbox', { name: 'Kontakte durchsuchen' }).fill(changedName);
  await expect(table).toContainText(changedName); expect(globalReads).toEqual([]);
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`contact-inventory-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`contact-inventory-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});

test('restored contact draft retains old revision after a real concurrent writer', async ({ page }) => {
  test.setTimeout(120_000);
  const { request, suffix } = await workspace(page);
  const contact = await request('/contacts', { company_name: `Original contact ${suffix}`, contact_type: 'supplier', country: 'DE' });
  let dialog = await edit(page, contact.company_name);
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  const draftName = `Draft contact ${suffix}`;
  await dialog.getByLabel('Firma', { exact: true }).fill(draftName);
  await expect(dialog.getByText('Persönlicher Entwurf gesichert', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  const concurrent = `Concurrent contact ${suffix}`;
  await request(`/contacts/${contact.id}`, { ...contact, company_name: concurrent }, 'put');
  dialog = await edit(page, concurrent);
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel('Firma', { exact: true })).toHaveValue(draftName);
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `/api/v1/contacts/${contact.id}` && reply.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await response).status()).toBe(412);
  await expect(dialog.locator('.edit-conflict-panel')).toBeVisible();
  await expect(dialog.getByLabel('Firma', { exact: true })).toHaveValue(draftName);
  expect((await request(`/contacts/${contact.id}`)).company_name).toBe(concurrent);
});
