import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('reviewed contract resumes a real lost-response draft and publishes immutable evidence once', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const unique = randomUUID();
  async function create(path, data) {
    const response = await page.request.post('/api/v1' + path, { headers, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  }
  const portfolio = await create('/portfolios', { name: `Wizard ${unique}` });
  const property = await create('/properties', { portfolio_id: portfolio.id, name: `Wizard property ${unique}`, property_type: 'residential' });
  const unit = await create('/units', { property_id: property.id, label: 'Reviewed A', unit_type: 'apartment',
    cold_rent: 600, service_charge_advance: 100, heating_advance: 50 });
  const original = Buffer.from('Synthetic original attachment: äöüß / 2026 / no private data');
  const upload = await page.request.post('/api/v1/files/upload?folder=documents', { headers,
    multipart: { file: { name: 'synthetic-original.txt', mimeType: 'text/plain', buffer: original } } });
  expect(upload.status()).toBe(200);
  const source = await create('/documents', { property_id: property.id, unit_id: unit.id,
    title: `Original ${unique}`, document_type: 'other', file_url: (await upload.json()).file_url });
  const financeBefore = {};
  for (const key of ['bookings', 'deposits']) {
    const response = await page.request.get('/api/v1/' + key, { headers });
    expect(response.status()).toBe(200); financeBefore[key] = (await response.json()).length;
  }
  await page.goto('/contract-wizard');
  await page.getByRole('button', { name: 'Neuen Entwurf vorbereiten', exact: true }).click();
  await page.getByLabel('Immobilie: Suchen', { exact: true }).fill(unique);
  await expect(page.getByLabel('Immobilie *', { exact: true })).toContainText(property.name);
  await page.getByLabel('Immobilie *', { exact: true }).selectOption(property.id);
  await expect(page.getByLabel('Einheit *', { exact: true })).toContainText(unit.label);
  await page.getByLabel('Einheit *', { exact: true }).selectOption(unit.id);
  await page.getByLabel('Vermieter / vollständiger Name *', { exact: true }).fill('Synthetic owner Änne');
  await page.getByLabel('Vermieteranschrift *', { exact: true }).fill('Synthetic street 12\n12345 Example');
  await page.getByLabel('Mieter / vollständiger Name *', { exact: true }).fill(`Synthetic new tenant ${unique}`);
  await page.getByLabel('Vertragsnummer *', { exact: true }).fill(`Wizard-${unique}`);
  await page.getByLabel('Mietbeginn *', { exact: true }).fill('2026-10-01');
  await page.getByLabel('Vereinbarte Kaution', { exact: true }).fill('1500.00');
  await page.getByLabel('Eigene Vereinbarungen / vollständiger Text', { exact: true }).fill('Own reviewed synthetic terms. No third-party clauses. äöüß € <literal>');
  await page.getByLabel('Unbestätigten Einzugs-Übergabeentwurf vorbereiten (keine Schlüssel / Unterschriften)', { exact: true }).check();
  const attachment = page.getByLabel('Anlage aus den Objektdokumenten', { exact: true });
  await expect(attachment).toContainText(source.title); await attachment.selectOption(source.id);
  await page.getByRole('button', { name: 'Anlage hinzufügen', exact: true }).click();
  let saved;
  await page.route('**/api/v1/contract-wizard/drafts', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const response = await route.fetch();
    expect(response.status()).toBe(201); saved = await response.json();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: 'Entwurf speichern', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Denselben Vorgang sicher wiederholen', exact: true })).toBeVisible();
  await expect(page.getByLabel('Vertragsnummer *', { exact: true })).toHaveValue(`Wizard-${unique}`);
  await page.unroute('**/api/v1/contract-wizard/drafts');
  await page.getByRole('button', { name: 'Denselben Vorgang sicher wiederholen', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`draft=${saved.id}`));
  await page.reload();
  await expect(page.getByLabel('Vertragsnummer *', { exact: true })).toHaveValue(`Wizard-${unique}`);
  await page.getByRole('button', { name: 'Gespeicherten Stand prüfen', exact: true }).click();
  await expect(page.getByRole('heading', { name: '4 · Prüfstand und Vorschau', exact: true })).toBeVisible();
  const reviewed = await (await page.request.get(`/api/v1/contract-wizard/drafts/${saved.id}`, { headers })).json();
  expect(reviewed.state).toBe('reviewed'); expect(reviewed.contract_id).toBeNull();
  await page.getByRole('button', { name: 'Geprüften Vertrag bestätigen & anlegen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Abbrechen', exact: true }).click();
  expect((await (await page.request.get(`/api/v1/contract-wizard/drafts/${saved.id}`, { headers })).json()).contract_id).toBeNull();
  await page.getByRole('button', { name: 'Geprüften Vertrag bestätigen & anlegen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Vertrag und Belege angelegt', exact: true })).toBeVisible();
  const published = await (await page.request.get(`/api/v1/contract-wizard/drafts/${saved.id}`, { headers })).json();
  expect(published.pdf_sha256).toBe(reviewed.pdf_sha256);
  const contract = await (await page.request.get(`/api/v1/contracts/${published.contract_id}`, { headers })).json();
  expect(contract).toMatchObject({ status: 'draft', deposit_amount: 1500, property_id: property.id, unit_id: unit.id });
  for (const key of ['bookings', 'deposits'])
    expect((await (await page.request.get('/api/v1/' + key, { headers })).json()).length).toBe(financeBefore[key]);
  const pdfDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Unveränderliches Vertrags-PDF herunterladen', exact: true }).click();
  const pdf = await readFile(await (await pdfDownload).path());
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(createHash('sha256').update(pdf).digest('hex')).toBe(published.pdf_sha256);
  const originalDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Archiviertes Original herunterladen', exact: true }).click();
  expect(await readFile(await (await originalDownload).path())).toEqual(original);
  await page.getByRole('button', { name: 'Manuelle Unterzeichnung erfassen', exact: true }).click();
  await page.getByLabel('Nachvollziehbare Belegreferenz', { exact: true }).fill(`Synthetic paper original ${unique}`);
  await page.getByRole('button', { name: 'Unterzeichnungsbeleg bestätigen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Unterzeichnungsbeleg bestätigen', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText(`Synthetic paper original ${unique}`, { exact: false })).toBeVisible();
  expect((await (await page.request.get(`/api/v1/contracts/${published.contract_id}`, { headers })).json()).status).toBe('draft');
  await page.setViewportSize({ width: 360, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const screenshot = testInfo.outputPath('reviewed-contract-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('reviewed-contract-mobile', { path: screenshot, contentType: 'image/png' });
});
