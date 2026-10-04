import { randomUUID } from 'node:crypto';
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
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy(); return response.json();
  };
  const suffix = randomUUID().slice(0, 8); const actor = await request('/auth/me');
  const portfolio = await request('/portfolios', { name: `Meter ${suffix}` });
  const property = await request('/properties', { portfolio_id: portfolio.id, name: `Meterhaus ${suffix}`, property_type: 'residential' });
  const unit = await request('/units', { property_id: property.id, label: `Meterwohnung ${suffix}`, unit_type: 'apartment' });
  const draft = (collection, entity, formKey = 'crud') => request(`/auth/users/me/form-drafts?${new URLSearchParams({ collection, owner_id: actor.id, form_key: formKey, ...(entity ? { entity_id: entity } : {}) })}`);
  const forbidden = [];
  page.on('request', event => { if (event.method() === 'GET' && ['/api/v1/meters', '/api/v1/meters/readings/all', '/api/v1/units', '/api/v1/properties'].includes(new URL(event.url()).pathname)) forbidden.push(event.url()); });
  return { request, headers, suffix, property, unit, draft, forbidden };
}

async function search(page, serial) {
  await page.goto('/meters'); await page.getByRole('searchbox', { name: 'Zähler durchsuchen' }).fill(serial);
}
async function edit(page, serial) {
  await search(page, serial); await page.getByRole('button', { name: `${serial} bearbeiten`, exact: true }).click();
  return page.getByRole('dialog', { name: 'Zähler bearbeiten', exact: true });
}

test('meters: complete filtered pages/CSV and bounded originals on desktop and narrow screens', async ({ page }, testInfo) => {
  test.setTimeout(120_000); const box = await workspace(page); const prefix = `Bounded ${box.suffix}`;
  const rows = [];
  for (let index = 0; index < 27; index += 1) rows.push(await box.request('/meters', { unit_id: box.unit.id,
    serial_number: `${prefix}-${String(index).padStart(2, '0')}`, meter_type: 'district_loop_x', measurement_unit: index === 26 ? null : 'therm-custom', is_active: index !== 0 }));
  const selected = rows.at(-1); const originals = [];
  for (let index = 0; index < 31; index += 1) originals.push(await box.request(`/meters/${selected.id}/readings`, { meter_id: selected.id,
    reading_date: `2026-01-${String(Math.floor(index / 2) + 1).padStart(2, '0')}`, value: index / 8, notes: `Original ${index}` }));
  const latest = [...originals].sort((a, b) => b.reading_date.localeCompare(a.reading_date) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0))[0];
  const proof = await box.request(`/meters/inventory/page?${new URLSearchParams({ search: selected.serial_number })}`);
  expect(proof.items[0]).toMatchObject({ last_reading_id: latest.id, last_reading_value: latest.value, measurement_unit: null });
  await search(page, prefix);
  await expect(page.getByRole('region', { name: 'Kennzahlen der gefilterten Zähler' })).toContainText('27Zähler gesamt');
  await expect(page.getByRole('button', { name: `${selected.serial_number} Ablesungen anzeigen`, exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await page.getByRole('button', { name: `${selected.serial_number} Ablesungen anzeigen`, exact: true }).click();
  const region = page.getByRole('region', { name: 'Ablesungen des geöffneten Zählers' });
  await expect(region).toContainText('Ungeklärt');
  await expect(region.getByRole('row')).toHaveCount(26);
  await region.getByRole('button', { name: 'Nächste Ableseseite', exact: true }).click();
  await expect(region.getByRole('row')).toHaveCount(7);
  const exportResponse = await page.request.get(`/api/v1/meters/inventory/export?${new URLSearchParams({ search: prefix })}`, { headers: box.headers });
  expect(exportResponse.ok()).toBeTruthy(); const csv = await exportResponse.text();
  expect(csv.split('\r\n').filter(Boolean)).toHaveLength(28); expect(csv).toContain(selected.id); expect(csv).toContain('therm-custom');
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`meters-${width}.png`); await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`meters-${width}`, { path: screenshot, contentType: 'image/png' });
  }
  expect(box.forbidden).toEqual([]);
});

test('meters: encrypted draft restores bounded unit selection and original revision conflicts with a real independent writer', async ({ page }) => {
  test.setTimeout(120_000); const box = await workspace(page);
  const candidates = [];
  for (let index = 0; index < 26; index += 1) candidates.push(await box.request('/units', { property_id: box.property.id, label: `Choice ${box.suffix}-${String(index).padStart(2, '0')}`, unit_type: 'apartment' }));
  const target = [...candidates].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)[0];
  const original = await box.request('/meters', { unit_id: box.unit.id, serial_number: `Original ${box.suffix}`, meter_type: 'district_loop_x', measurement_unit: 'therm-custom', is_active: false, contract_number: 'Preserved original contract' });
  let dialog = await edit(page, original.serial_number); await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel('Seriennummer', { exact: true }).fill(`Draft ${box.suffix}`);
  const choices = dialog.getByRole('group', { name: /^Einheit/ });
  await choices.getByRole('searchbox', { name: 'Einheit suchen' }).fill(`Choice ${box.suffix}`);
  await expect(choices.getByRole('button', { name: target.label, exact: true })).toHaveCount(0);
  await choices.getByRole('button', { name: 'Nächste Auswahlseite', exact: true }).click();
  await choices.getByRole('button', { name: target.label, exact: true }).click();
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click(); await expect(dialog).toHaveCount(0);
  const stored = (await box.draft('meters', original.id)).draft;
  expect(stored.values.unit_id).toBe(target.id); expect(stored.edit_revision.updatedAt).toBe(original.updated_at);
  const concurrent = await box.request(`/meters/${original.id}`, { ...original, serial_number: `Writer ${box.suffix}` }, 'put');
  await page.reload(); dialog = await edit(page, concurrent.serial_number);
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel('Seriennummer', { exact: true })).toHaveValue(`Draft ${box.suffix}`);
  await expect(dialog).toContainText(`Ausgewählt: ${target.label}`);
  await expect(dialog.getByLabel('Tatsächliche Maßeinheit', { exact: true })).toHaveValue('therm-custom');
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `/api/v1/meters/${original.id}` && reply.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); expect((await response).status()).toBe(412);
  await expect(dialog.locator('.edit-conflict-panel')).toBeVisible();
  await expect(dialog.getByLabel('Seriennummer', { exact: true })).toHaveValue(`Draft ${box.suffix}`);
  expect((await box.request(`/meters/${original.id}`)).serial_number).toBe(concurrent.serial_number);
  expect(box.forbidden).toEqual([]);
});

test('meters: lost successful reading POST survives reload and is reconciled against the actual bounded history', async ({ page }) => {
  test.setTimeout(120_000); const box = await workspace(page);
  const meter = await box.request('/meters', { unit_id: box.unit.id, serial_number: `Reading ${box.suffix}`, meter_type: 'cold_water', measurement_unit: null });
  await search(page, meter.serial_number); await page.getByRole('button', { name: `${meter.serial_number} Ablesungen anzeigen`, exact: true }).click();
  await page.getByRole('button', { name: 'Ablesung erfassen', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: `Ablesung erfassen · ${meter.serial_number}`, exact: true });
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel('Ablesedatum', { exact: false }).fill('2026-10-02'); await dialog.getByLabel('Zählerstand', { exact: false }).fill('124.125');
  await dialog.getByLabel('Notizen', { exact: true }).fill(`Lost ${box.suffix}`);
  let posts = 0;
  await page.route(`**/api/v1/meters/${meter.id}/readings`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    posts += 1; const saved = await route.fetch(); expect(saved.status()).toBe(201);
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Gespeichert, Antwort verloren' }) });
  });
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog.getByRole('alert').filter({ hasText: 'Gespeichert, Antwort verloren' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
  const proof = await box.request(`/meters/${meter.id}/readings/page`); expect(proof.items).toHaveLength(1);
  expect(proof.items[0]).toMatchObject({ value: 124.125, reading_date: '2026-10-02', meter_id: meter.id });
  expect((await box.draft('meters/readings', null, `meter:${meter.id}`)).draft.submission_pending).toBe(true);
  await page.reload(); await search(page, meter.serial_number); await page.getByRole('button', { name: `${meter.serial_number} Ablesungen anzeigen`, exact: true }).click();
  await expect(page.getByRole('region', { name: 'Ablesungen des geöffneten Zählers' })).toContainText(`Lost ${box.suffix}`);
  await page.getByRole('button', { name: 'Ablesung erfassen', exact: true }).click(); dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Prüfen Sie zuerst den aktuellen Bestand');
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Gespeicherten Entwurf verwerfen', exact: true }).click();
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible(); await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  expect((await box.request(`/meters/${meter.id}/readings/page`)).items).toHaveLength(1); expect(posts).toBe(1); expect(box.forbidden).toEqual([]);
});
