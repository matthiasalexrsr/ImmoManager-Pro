import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function workspace(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  const headers = { Authorization: `Bearer ${token}` };
  const request = async (path, data, method = data === undefined ? 'get' : 'post') => {
    const response = await page.request[method](`/api/v1${path}`, { headers, ...(data === undefined ? {} : { data }) });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const owner = await request('/auth/me');
  const suffix = randomUUID().slice(0, 8);
  const portfolio = await request('/portfolios', { name: `Entwurfsbestand ${suffix}` });
  const property = await request('/properties', { portfolio_id: portfolio.id, name: `Original ${suffix}`, property_type: 'residential' });
  const draft = (entity = property.id) => request(`/auth/users/me/form-drafts?${new URLSearchParams({ collection: 'properties', form_key: 'crud', owner_id: owner.id, ...(entity ? { entity_id: entity } : {}) })}`);
  const discard = async (entity = property.id) => {
    const saved = (await draft(entity)).draft;
    if (saved) await request(`/auth/users/me/form-drafts?${new URLSearchParams({ collection: 'properties', form_key: 'crud', owner_id: owner.id, expected_revision: saved.revision, ...(entity ? { entity_id: entity } : {}) })}`, undefined, 'delete');
  };
  return { owner, suffix, portfolio, property, request, draft, discard };
}

async function edit(page, property) {
  await page.goto('/properties');
  await page.getByRole('button', { name: `${property.name} bearbeiten`, exact: true }).click();
  return page.getByRole('dialog');
}

test('encrypted draft survives reload, restores explicitly and saves the business record once', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const data = await workspace(page);
  const name = `Wiederaufgenommen ${data.suffix}`;
  let dialog = await edit(page, data.property);
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel(/^Objektname/).fill(name);
  await expect(dialog.getByText('Persönlicher Entwurf gesichert', { exact: true })).toBeVisible();
  const stored = (await data.draft()).draft;
  expect(stored.values.name).toBe(name);
  expect(stored.edit_revision.updatedAt).toContain(data.property.updated_at.slice(0, 19));
  expect((await data.request(`/properties/${data.property.id}`)).name).toBe(data.property.name);
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await page.reload();
  dialog = await edit(page, data.property);
  await expect(dialog.getByText('Früheren Entwurf wiederaufnehmen', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel(/^Objektname/)).toHaveValue(data.property.name);
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel(/^Objektname/)).toHaveValue(name);
  for (const theme of ['light', 'dark']) {
    await page.evaluate(value => document.documentElement.setAttribute('data-theme', value), theme);
    await page.setViewportSize({ width: 320, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`draft-320-${theme}.png`) });
  }
  const saves = [];
  page.on('request', request => { if (new URL(request.url()).pathname === `/api/v1/properties/${data.property.id}` && request.method() === 'PUT') saves.push(request); });
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect((await data.request(`/properties/${data.property.id}`)).name).toBe(name);
  expect((await data.draft()).draft).toBeNull();
  expect(saves).toHaveLength(1);
});

test('two native tabs preserve the losing draft and restored original CAS after another writer', async ({ page }) => {
  test.setTimeout(120_000);
  const data = await workspace(page);
  const other = await page.context().newPage();
  try {
    const first = await edit(page, data.property);
    const second = await edit(other, data.property);
    await expect(first.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
    await expect(second.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
    await first.getByLabel(/^Objektname/).fill(`Fenster A ${data.suffix}`);
    await expect(first.getByText('Persönlicher Entwurf gesichert', { exact: true })).toBeVisible();
    await second.getByLabel(/^Objektname/).fill(`Fenster B ${data.suffix}`);
    await expect(second.getByText('Entwurf wurde in einem anderen Fenster geändert', { exact: true })).toBeVisible();
    await expect(second.getByLabel(/^Objektname/)).toHaveValue(`Fenster B ${data.suffix}`);
    expect((await data.draft()).draft.values.name).toBe(`Fenster A ${data.suffix}`);
    await second.getByRole('button', { name: 'Ohne weitere Entwurfssicherung schließen', exact: true }).click();
    await first.getByRole('button', { name: 'Abbrechen', exact: true }).click();
    // A real API writer changes the record while the saved original token stays old.
    await data.request(`/properties/${data.property.id}`, { ...data.property, name: `Dritte Änderung ${data.suffix}` }, 'put');
    const restored = await edit(page, { ...data.property, name: `Dritte Änderung ${data.suffix}` });
    await restored.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
    await expect(restored.getByLabel(/^Objektname/)).toHaveValue(`Fenster A ${data.suffix}`);
    const response = page.waitForResponse(item => new URL(item.url()).pathname === `/api/v1/properties/${data.property.id}` && item.request().method() === 'PUT');
    await restored.getByRole('button', { name: 'Speichern', exact: true }).click();
    expect((await response).status()).toBe(412);
    await expect(restored.getByLabel(/^Objektname/)).toHaveValue(`Fenster A ${data.suffix}`);
    await expect(restored.locator('.edit-conflict-panel')).toBeVisible();
    expect((await data.request(`/properties/${data.property.id}`)).name).toBe(`Dritte Änderung ${data.suffix}`);
  } finally { await other.close(); await data.discard(); }
});

test('confirmed creation with failed draft cleanup cannot replay and next reopen demands review', async ({ page }) => {
  test.setTimeout(120_000);
  const data = await workspace(page);
  await page.goto('/properties');
  await page.getByRole('button', { name: 'Immobilie anlegen', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel(/^Portfolio/).selectOption(data.portfolio.id);
  await dialog.getByLabel(/^Objektname/).fill(`Einmal angelegt ${data.suffix}`);
  await dialog.getByLabel(/^Objektart/).selectOption('residential');
  await page.route('**/api/v1/auth/users/me/form-drafts?*', async route => {
    if (route.request().method() === 'DELETE') await route.fulfill({ status: 503, json: { error: { code: 'TEST_CLEANUP_UNAVAILABLE', message: 'Bereinigung vorübergehend nicht verfügbar' } } });
    else await route.continue();
  });
  const creations = [];
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/v1/properties' && request.method() === 'POST') creations.push(request); });
  const created = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/properties' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const result = await created;
  expect(result.status()).toBe(201);
  const row = await result.json();
  await expect(dialog.getByText('Der Datensatz wurde gespeichert.', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
  expect((await data.request(`/properties/${row.id}`)).name).toBe(`Einmal angelegt ${data.suffix}`);
  expect((await data.draft(null)).draft.submission_pending).toBe(true);
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).last().click();
  await page.reload();
  await page.getByRole('button', { name: 'Immobilie anlegen', exact: true }).first().click();
  await expect(dialog.getByText(/Der frühere Speichervorgang wurde begonnen/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Nach Bestandsprüfung weiterbearbeiten', exact: true })).toBeVisible();
  await expect(dialog.getByLabel(/^Objektname/)).toHaveValue('');
  expect(creations).toHaveLength(1);
  // Independent suites share the real database. Explicitly resolve this test's
  // intentionally retained create marker before another normal owner form opens.
  await page.unroute('**/api/v1/auth/users/me/form-drafts?*');
  await dialog.getByRole('button', { name: 'Gespeicherten Entwurf verwerfen', exact: true }).click();
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  expect((await data.draft(null)).draft).toBeNull();
});

test('meter edit restores only metadata and refreshes the visible source after cleanup', async ({ page }) => {
  test.setTimeout(120_000);
  const data = await workspace(page);
  const unit = await data.request('/units', { property_id: data.property.id, label: `Entwurfseinheit ${data.suffix}`, unit_type: 'apartment' });
  const meter = await data.request('/meters', { unit_id: unit.id, meter_type: 'cold_water', serial_number: `Draft-${data.suffix}`, supplier: 'Originalquelle' });
  const openMeter = async () => {
    await page.goto('/meters');
    await page.getByRole('row').filter({ hasText: meter.serial_number }).click();
    await page.getByRole('button', { name: 'Zähler bearbeiten', exact: true }).click();
    return page.getByRole('dialog');
  };
  let dialog = await openMeter();
  await expect(dialog.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await dialog.getByLabel('Versorger', { exact: true }).fill(`Neue Quelle ${data.suffix}`);
  await expect(dialog.getByText('Persönlicher Entwurf gesichert', { exact: true })).toBeVisible();
  expect((await data.request(`/meters/${meter.id}`)).supplier).toBe('Originalquelle');
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await page.reload();
  dialog = await openMeter();
  await dialog.getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
  await expect(dialog.getByLabel('Versorger', { exact: true })).toHaveValue(`Neue Quelle ${data.suffix}`);
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: meter.serial_number })).toContainText(`Neue Quelle ${data.suffix}`);
  const record = await data.request(`/meters/${meter.id}`);
  expect(record.supplier).toBe(`Neue Quelle ${data.suffix}`);
  const readings = await data.request(`/meters/${meter.id}/readings`);
  expect(readings).toHaveLength(0);
});
