import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const forms = [
  { collection: 'units', key: 'label', field: 'Bezeichnung', search: 'Einheiten durchsuchen', dialog: 'Einheit bearbeiten' },
  { collection: 'documents', key: 'title', field: 'Titel', search: 'Dokumente durchsuchen', dialog: 'Dokument bearbeiten' },
  { collection: 'maintenance', key: 'title', field: 'Titel', search: 'Wartungsfälle durchsuchen', dialog: 'Wartungsfall bearbeiten' },
];
async function workspace(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const request = async (path, data, method = data === undefined ? 'get' : 'post') => {
    const reply = await page.request[method](`/api/v1${path}`, { headers, ...(data === undefined ? {} : { data }) });
    expect(reply.ok(), `${path}: ${await reply.text()}`).toBeTruthy(); return reply.json();
  };
  const owner = await request('/auth/me');
  const suffix = randomUUID().slice(0, 8);
  const portfolio = await request('/portfolios', { name: `Draft ${suffix}` });
  const properties = [];
  for (let index = 0; index < 26; index += 1) properties.push(await request('/properties', {
    portfolio_id: portfolio.id, name: `Drafthaus ${suffix}-${String(index).padStart(2, '0')}`, property_type: 'residential',
  }));
  // Choices use descending bytewise IDs, independently of creation order/name.
  const target = [...properties].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)[0];
  const source = properties.find(property => property.id !== target.id);
  const unit = await request('/units', { property_id: target.id, label: `Draftwohnung ${suffix}`, unit_type: 'apartment' });
  const tenant = await request('/tenants', { full_name: `Synthetic Draft Tenant ${suffix}` });
  const contract = await request('/contracts', { property_id: target.id, unit_id: unit.id, tenant_id: tenant.id,
    contract_number: `Draftvertrag ${suffix}`, start_date: '2026-01-01', status: 'draft' });
  const draft = (collection, entity) => request(`/auth/users/me/form-drafts?${new URLSearchParams({ collection, owner_id: owner.id, form_key: 'crud', ...(entity ? { entity_id: entity } : {}) })}`);
  return { request, headers, suffix, source, target, unit, contract, draft };
}
async function edit(page, item, name) {
  await page.goto(`/${item.collection}`);
  await page.getByRole('searchbox', { name: item.search }).fill(name);
  await page.getByRole('button', { name: `${name} bearbeiten`, exact: true }).click();
  return page.getByRole('dialog', { name: item.dialog, exact: true });
}
async function references(dialog, box, item) {
  const propertyChoice = dialog.getByRole('group', { name: /^Immobilie/ });
  await propertyChoice.getByRole('searchbox', { name: 'Immobilie suchen' }).fill(`Drafthaus ${box.suffix}`);
  await expect(propertyChoice.getByRole('button', { name: box.target.name, exact: true })).toHaveCount(0);
  await propertyChoice.getByRole('button', { name: 'Nächste Auswahlseite', exact: true }).click();
  await propertyChoice.getByRole('button', { name: box.target.name, exact: true }).click();
  if (item.collection !== 'units') {
    await dialog.getByRole('searchbox', { name: 'Einheit suchen' }).fill(box.unit.label);
    await dialog.getByRole('button', { name: box.unit.label, exact: true }).click();
  }
  if (item.collection === 'documents') {
    await dialog.getByRole('searchbox', { name: 'Vertrag suchen' }).fill(box.contract.contract_number);
    await dialog.getByRole('button', { name: new RegExp(`^${box.contract.contract_number}`) }).click();
  }
}

for (const item of forms) test(`${item.collection}: encrypted reload restores bounded references and stale revision yields real 412`, async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const box = await workspace(page);
  let uploaded;
  if (item.collection === 'documents') {
    const upload = await page.request.post('/api/v1/files/upload', { headers: box.headers, multipart: { file: { name: `source-${box.suffix}.txt`, mimeType: 'text/plain', buffer: Buffer.from('Synthetic original document.\n') } } });
    expect(upload.ok(), await upload.text()).toBeTruthy(); uploaded = await upload.json();
  }
  const extra = item.collection === 'units' ? { unit_type: 'apartment', features: 'Originale Ausstattung', cold_rent: 0 }
    : item.collection === 'documents' ? { document_type: 'Rechnung', file_url: uploaded.file_url, description: 'Originaler vollständiger Dokumenttext' }
      : { description: 'Originaler vollständiger Falltext', appointment_at: '2026-11-01T15:30:45.123456', estimated_cost: 0 };
  const original = await box.request(`/${item.collection}`, { [item.key]: `Original ${box.suffix}`, property_id: box.source.id, ...extra });
  const forbidden = [];
  page.on('request', request => { if (request.method() === 'GET' && ['/api/v1/units', '/api/v1/documents', '/api/v1/maintenance', '/api/v1/properties', '/api/v1/contracts'].includes(new URL(request.url()).pathname)) forbidden.push(request.url()); });
  let dialog = await edit(page, item, original[item.key]);
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel(item.field, { exact: false }).fill(`Entwurf ${box.suffix}`);
  await references(dialog, box, item);
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const savedDraft = (await box.draft(item.collection, original.id)).draft;
  expect(savedDraft.values.property_id).toBe(box.target.id);
  if (item.collection !== 'units') expect(savedDraft.values.unit_id).toBe(box.unit.id);
  if (item.collection === 'documents') expect(savedDraft.values.contract_id).toBe(box.contract.id);
  if (item.collection === 'maintenance') expect(savedDraft.original_values.appointment_at).toBe(original.appointment_at);
  const concurrentName = `Concurrent ${box.suffix}`;
  await box.request(`/${item.collection}/${original.id}`, { ...original, [item.key]: concurrentName }, 'put');
  await page.reload(); dialog = await edit(page, item, concurrentName);
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel(item.field, { exact: false })).toHaveValue(`Entwurf ${box.suffix}`);
  await expect(dialog).toContainText(`Ausgewählt: ${box.target.name}`);
  if (item.collection !== 'units') await expect(dialog).toContainText(`Ausgewählt: ${box.unit.label}`);
  if (item.collection === 'maintenance') await expect(dialog.getByLabel('Termin mit Uhrzeit')).toHaveValue(/2026-11-01T15:30:45(?:\.000)?/);
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`${item.collection}-draft-${width}.png`);
    await page.screenshot({ path: screenshot }); await testInfo.attach(`${item.collection}-draft-${width}`, { path: screenshot, contentType: 'image/png' });
  }
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `/api/v1/${item.collection}/${original.id}` && reply.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const failed = await response; expect(failed.status()).toBe(412);
  if (item.collection === 'maintenance') expect(failed.request().postDataJSON().appointment_at).toBe(original.appointment_at);
  await expect(dialog.locator('.edit-conflict-panel')).toBeVisible();
  await expect(dialog.getByLabel(item.field, { exact: false })).toHaveValue(`Entwurf ${box.suffix}`);
  expect((await box.request(`/${item.collection}/${original.id}`))[item.key]).toBe(concurrentName);
  expect(forbidden).toEqual([]);
});

test('documents: create draft retains uploaded original on reload and lost successful response cannot silently repeat POST', async ({ page }) => {
  test.setTimeout(120_000);
  const box = await workspace(page); const title = `Createentwurf ${box.suffix}`;
  await page.goto('/documents'); await page.getByRole('button', { name: 'Dokument erstellen', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: 'Dokument erstellen', exact: true });
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel('Titel', { exact: false }).fill(title);
  await dialog.getByLabel('Datei auswählen', { exact: true }).setInputFiles({ name: `draft-${box.suffix}.txt`, mimeType: 'text/plain', buffer: Buffer.from('Synthetic retained draft original.\n') });
  await expect(dialog).toContainText('Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.');
  await references(dialog, box, forms[1]);
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click(); await expect(dialog).toHaveCount(0);
  const fileUrl = (await box.draft('documents')).draft.values.file_url; expect(fileUrl).toContain('/uploads/');
  await page.reload(); await page.getByRole('button', { name: 'Dokument erstellen', exact: true }).click();
  dialog = page.getByRole('dialog', { name: 'Dokument erstellen', exact: true });
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel('Titel', { exact: false })).toHaveValue(title);
  await expect(dialog).toContainText('Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.');
  let postCount = 0;
  await page.route('**/api/v1/documents', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    postCount += 1; const created = await route.fetch(); expect(created.status()).toBe(201);
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Gespeichert, Antwort verloren' }) });
  });
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert').filter({ hasText: 'Gespeichert, Antwort verloren' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
  const proof = await box.request(`/documents/inventory/page?${new URLSearchParams({ search: title })}`);
  expect(proof.items).toHaveLength(1); expect(proof.items[0]).toMatchObject({ title, file_url: fileUrl, property_id: box.target.id, unit_id: box.unit.id, contract_id: box.contract.id });
  const original = await page.request.get(fileUrl, { headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` } });
  expect(original.ok()).toBeTruthy(); expect(await original.text()).toBe('Synthetic retained draft original.\n');
  await page.reload(); await page.getByRole('button', { name: 'Dokument erstellen', exact: true }).click();
  dialog = page.getByRole('dialog', { name: 'Dokument erstellen', exact: true });
  await expect(dialog).toContainText('Prüfen Sie zuerst den aktuellen Bestand');
  expect((await box.request(`/documents/inventory/page?${new URLSearchParams({ search: title })}`)).items).toHaveLength(1);
  await dialog.getByRole('button', { name: 'Gespeicherten Entwurf verwerfen', exact: true }).click();
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Dokumente durchsuchen' }).fill(title);
  await expect(page.getByRole('button', { name: title, exact: true })).toBeVisible();
  expect(postCount).toBe(1); expect((await box.draft('documents')).draft).toBeNull();
});
