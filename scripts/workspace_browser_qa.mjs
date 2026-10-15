// Run only against a disposable local QA installation with environment credentials.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || base.pathname !== '/' || base.username || process.env.QA_ALLOW_TEST_WRITES !== '1' || !process.env.QA_PASSWORD || !process.env.QA_PLAYWRIGHT_PATH) throw new Error('Disposable loopback QA settings required.');
const { chromium, request, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
const out = path.resolve(process.env.QA_OUTPUT);
await fs.mkdir(out, { recursive: true });
const result = { syntheticOnly: true, checks: [], errors: [], screenshots: [] };
const browser = await chromium.launch({ channel: 'chromium', headless: true });
result.browserVersion = browser.version();
let api, context, page;
async function call(method, route, data) {
  const response = await api.fetch(`/api/v1${route}`, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, operation) {
  try { await operation(); result.checks.push({ name, passed: true }); console.log(`PASS ${name}`); }
  catch (error) { result.checks.push({ name, passed: false, error: String(error) }); await page?.screenshot({ path: path.join(out, `failure-${result.checks.length}.png`), fullPage: true }).catch(() => {}); throw error; }
  finally { await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2)); }
}
async function login(username = 'owner') {
  await page.goto(`${base.origin}/login`);
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  const later = page.getByRole('button', { name: 'Später', exact: true });
  if (await later.isVisible().catch(() => false)) await later.click();
}
const tenantRow = name => page.locator('.data-table tbody tr').filter({ hasText: name });
function fixturePdf(text) {
  const content = `BT /F1 18 Tf 50 750 Td (${text}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`];
  let data = '%PDF-1.4\n'; const offsets = [];
  for (let index = 0; index < objects.length; index++) { offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`; }
  const start = Buffer.byteLength(data);
  return Buffer.from(data + `xref\n0 6\n0000000000 65535 f \n${offsets.map(value => `${String(value).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`);
}
async function editTenant(name) {
  await page.goto(`${base.origin}/tenants`);
  // The list deliberately remembers the previous search; start this new lookup
  // with an explicit clear rather than depending on changing row-count titles.
  await page.locator('.data-table-wrapper .search-input').fill('');
  await tenantRow(name).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Mieter bearbeiten' });
  await expect(dialog.getByLabel('Vollständiger Name', { exact: false })).toBeEnabled();
  return dialog;
}
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const response = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok(), 'Disposable owner login failed');
  const tokens = await response.json(); await setup.dispose();
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${tokens.access_token}` } });
  const profile = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Arbeitsalltag' });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Haus Äußere Straße', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'QA Wohnung 1', unit_type: 'residential', cold_rent: 500 });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Anna Beispiel', email: 'anna@example.invalid' });
  await call('POST', '/contracts', { contract_number: 'QA-MV-1', property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-01-01', status: 'active' });
  const task = await call('POST', '/tasks', { title: 'QA Rückruf Handwerker', status: 'open', property_id: property.id, due_date: '2026-10-20' });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })); }, profile.id);
  page = await context.newPage(); page.on('pageerror', error => result.errors.push(String(error))); page.setDefaultTimeout(15000);
  await step('Real login and exact source navigation', async () => { await login(); await page.goto(`${base.origin}/tasks?focus_id=${task.id}`); await expect(page.getByText('QA Rückruf Handwerker', { exact: true })).toBeVisible(); });
  await step('Autosave preserves an edit without changing the tenant', async () => {
    const dialog = await editTenant(tenant.full_name);
    await dialog.getByLabel('Vollständiger Name', { exact: false }).fill('QA Anna Entwurf');
    await expect(dialog.getByText('Entwurf automatisch gesichert')).toBeVisible();
    assert.equal((await call('GET', `/tenants/${tenant.id}`)).full_name, tenant.full_name);
    await page.reload();
    await tenantRow(tenant.full_name).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    await page.getByRole('button', { name: 'Entwurf wiederaufnehmen', exact: true }).click();
    await expect(page.getByLabel('Vollständiger Name', { exact: false })).toHaveValue('QA Anna Entwurf');
    await page.getByRole('button', { name: 'Abbrechen', exact: true }).click();
    await page.getByRole('button', { name: 'Verwerfen', exact: true }).click();
  });
  await step('Crash before debounce preserves the latest local draft', async () => {
    const dialog = await editTenant(tenant.full_name);
    await dialog.getByLabel('Vollständiger Name', { exact: false }).fill('QA Blitzentwurf');
    await page.reload();
    await tenantRow(tenant.full_name).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    await page.getByRole('button', { name: 'Entwurf wiederaufnehmen', exact: true }).click();
    await expect(page.getByLabel('Vollständiger Name', { exact: false })).toHaveValue('QA Blitzentwurf');
    await page.getByRole('button', { name: 'Abbrechen', exact: true }).click(); await page.getByRole('button', { name: 'Verwerfen', exact: true }).click();
  });
  await step('Named views survive reload and remain separate', async () => {
    const search = page.locator('.data-table-wrapper .search-input');
    await search.fill('QA Anna'); await page.getByLabel('Name der neuen Ansicht').fill('QA Parteienansicht');
    await page.getByRole('button', { name: 'Ansicht speichern', exact: true }).click();
    await expect(page.getByLabel('Ansicht', { exact: true })).toContainText('QA Parteienansicht');
    await search.fill('Keine Treffer'); await page.getByLabel('Name der neuen Ansicht').fill('QA Zweite Ansicht');
    await page.getByRole('button', { name: 'Ansicht speichern', exact: true }).click(); await page.reload();
    await page.getByLabel('Ansicht', { exact: true }).selectOption({ label: 'QA Parteienansicht' });
    await expect(page.locator('.data-table-wrapper .search-input')).toHaveValue('QA Anna');
  });
  await step('Entity favorites and recents use persistent authorized records', async () => {
    await page.goto(`${base.origin}/properties/${property.id}`);
    await page.getByRole('button', { name: `Als Favorit merken: ${property.name}` }).click();
    await expect(page.getByRole('button', { name: `Favorit entfernen: ${property.name}` })).toHaveAttribute('aria-pressed', 'true');
    assert.ok((await call('GET', '/workspace/favorites')).items.some(item => item.entity_id === property.id));
    assert.ok((await call('GET', '/workspace/recents')).items.some(item => item.entity_id === property.id));
    await page.goto(`${base.origin}/work-center`); await expect(page.getByRole('region', { name: 'Gemerkte Vorgänge' }).getByRole('link', { name: property.name })).toBeVisible();
  });
  await step('Conversation and followup are one atomic real workflow', async () => {
    await page.goto(`${base.origin}/properties/${property.id}`); await page.getByRole('button', { name: 'Gespräch / Wiedervorlage', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: new RegExp('Gespräch / Wiedervorlage') });
    await expect(dialog.getByLabel('Gesprächsnotiz')).toBeEnabled(); await dialog.getByLabel('Gesprächsnotiz').fill('QA Telefonat: Handwerker bestätigt Freitag.');
    await dialog.getByLabel('Aufgabe', { exact: true }).fill('QA Termin bestätigen'); await dialog.getByLabel('Fällig am', { exact: true }).fill('2026-10-23');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await expect(dialog).toHaveCount(0);
    const timeline = await call('GET', `/work-center/timeline?entity_type=property&entity_id=${property.id}`);
    assert.ok(JSON.stringify(timeline).includes('QA Telefonat')); assert.ok((await call('GET', '/tasks')).some(item => item.title === 'QA Termin bestätigen'));
  });
  await step('Inline task edit can be undone with a revision check', async () => {
    await page.goto(`${base.origin}/tasks?focus_id=${task.id}`); await page.getByRole('button', { name: `Status bearbeiten: ${task.title}` }).click();
    await page.getByLabel('Status', { exact: true }).selectOption('completed');
    await page.locator('.work-inline form').getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Rückgängig', exact: true })).toBeVisible(); assert.equal((await call('GET', `/tasks/${task.id}`)).status, 'completed');
    await page.getByRole('button', { name: 'Rückgängig', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/tasks/${task.id}`)).status).toBe('open');
  });
  await step('Document queue previews real PDFs and saves the next record with explicit assignment carry', async () => {
    const documents = [];
    for (const label of ['A', 'B']) {
      const upload = await api.post('/api/v1/files/upload?folder=documents', { multipart: {
        file: { name: `qa-queue-${label}.pdf`, mimeType: 'application/pdf', buffer: fixturePdf(`QA DOCUMENT QUEUE ${label}`) },
      } });
      assert.ok(upload.ok(), `Upload failed: ${await upload.text()}`);
      const file = await upload.json();
      documents.push(await call('POST', '/documents', { title: `QA Eingangsbeleg ${label}`, document_type: 'other', file_url: file.file_url }));
    }
    await page.goto(`${base.origin}/document-queue`);
    for (const document of documents) await page.getByLabel(`Auswählen: ${document.title}`, { exact: true }).check();
    await page.getByRole('button', { name: 'Auswahl analysieren (2)', exact: true }).click();
    await expect(page.getByText('2 analysiert', { exact: true })).toBeVisible();
    const ordered = (await call('GET', '/work-center/documents')).items.filter(row => documents.some(document => row.document_id === document.id));
    const first = documents.find(document => document.id === ordered[0].document_id);
    const second = documents.find(document => document.id === ordered[1].document_id);
    await page.locator('.work-queue-table tbody tr').filter({ hasText: first.title }).getByRole('button', { name: 'Vorschläge prüfen', exact: true }).click();
    let dialog = page.getByRole('dialog', { name: `Dokument prüfen · ${first.title}`, exact: true });
    await expect(dialog.getByLabel(/^Titel/)).toBeEnabled();
    await dialog.getByRole('button', { name: 'Original ansehen', exact: true }).click();
    const viewer = page.getByRole('dialog', { name: first.title, exact: true });
    await expect(viewer.getByRole('img', { name: new RegExp(`${first.title}.*Seite 1`) })).toBeVisible();
    await viewer.getByRole('button', { name: 'PDF-Text', exact: true }).click();
    await expect(viewer.locator('.pdf-preview-text')).toContainText('QA DOCUMENT QUEUE');
    await viewer.getByRole('button', { name: 'Schließen', exact: true }).click();
    await dialog.getByLabel('Immobilie', { exact: true }).selectOption(property.id);
    await dialog.getByLabel('Zuordnung für den nächsten unzugeordneten Beleg übernehmen', { exact: true }).check();
    await dialog.getByRole('button', { name: 'Speichern & nächster Beleg', exact: true }).click();
    dialog = page.getByRole('dialog', { name: `Dokument prüfen · ${second.title}`, exact: true });
    await expect(dialog.getByLabel(/^Titel/)).toHaveValue(second.title);
    await expect(dialog.getByLabel('Immobilie', { exact: true })).toHaveValue(property.id);
    assert.equal((await call('GET', `/documents/${first.id}`)).property_id, property.id);
    assert.equal((await call('GET', `/documents/${second.id}`)).property_id, null, 'Carry must remain a proposal until saved');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    assert.equal((await call('GET', `/documents/${second.id}`)).property_id, property.id);
    await page.getByRole('button', { name: 'Rückgängig', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/documents/${second.id}`)).property_id).toBe(null);
  });
  await step('Changed source requires comparison before recovering and saving a draft', async () => {
    const conflict = await call('POST', '/tenants', { full_name: 'QA Konfliktpartei' });
    const dialog = await editTenant(conflict.full_name);
    await dialog.getByLabel('Vollständiger Name', { exact: false }).fill('QA Verglichener Entwurf');
    await expect(dialog.getByText('Entwurf automatisch gesichert')).toBeVisible();
    await page.reload();
    await call('PATCH', `/tenants/${conflict.id}`, { full_name: 'QA Zwischenzeitlich geändert', updated_at: conflict.updated_at });
    await page.goto(`${base.origin}/tenants`);
    await tenantRow('QA Zwischenzeitlich geändert').getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    await page.getByRole('button', { name: 'Aktuellen Stand vergleichen', exact: true }).click();
    await expect(page.getByRole('dialog').getByRole('table').getByText('QA Zwischenzeitlich geändert', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Verglichenen Entwurf übernehmen', exact: true }).click();
    await expect(page.getByLabel('Vollständiger Name', { exact: false })).toHaveValue('QA Verglichener Entwurf');
    await page.getByRole('dialog').getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    assert.equal((await call('GET', `/tenants/${conflict.id}`)).full_name, 'QA Verglichener Entwurf');
  });
  await step('Party timeline shows readable field changes with before and after values', async () => {
    await tenantRow('QA Verglichener Entwurf').getByRole('button', { name: 'QA Verglichener Entwurf', exact: true }).click();
    const party = page.getByRole('dialog', { name: 'QA Verglichener Entwurf', exact: true });
    await party.getByRole('tab', { name: 'Aktivitäten', exact: true }).click();
    const change = party.locator('.work-timeline li').filter({ hasText: 'Änderung: Name' })
      .filter({ hasText: 'QA Zwischenzeitlich geändert' }).filter({ hasText: 'QA Verglichener Entwurf' });
    await expect(change).toHaveCount(1);
    await expect(change.getByText('Vorher', { exact: true })).toBeVisible();
    await expect(change.getByText('Nachher', { exact: true })).toBeVisible();
    await expect(change.getByText('QA Zwischenzeitlich geändert', { exact: true })).toBeVisible();
    await expect(change.getByText('QA Verglichener Entwurf', { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(out, 'party-timeline.png'), fullPage: false });
    result.screenshots.push('party-timeline.png');
    await party.getByRole('button', { name: 'Schließen', exact: true }).click();
    await expect(party).toHaveCount(0);
  });
  await step('Read-only user has private views and no domain writing controls', async () => {
    const ownerPage = page;
    const readerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await readerContext.addInitScript(id => {
      localStorage.setItem('locale', 'de-DE');
      if (id) localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true }));
    }, process.env.QA_READONLY_ID);
    try {
      page = await readerContext.newPage(); page.setDefaultTimeout(15000);
      page.on('pageerror', error => result.errors.push(String(error)));
      await login('steuerberater');
      await page.goto(`${base.origin}/tenants`);
      await expect(page.locator('.data-table tbody')).toContainText(tenant.full_name);
      await expect(page.getByLabel('Ansicht', { exact: true })).not.toContainText('QA Parteienansicht');
      assert.equal(await page.getByRole('button', { name: 'Bearbeiten', exact: true }).count(), 0);
      await page.goto(`${base.origin}/properties/${property.id}`);
      assert.equal(await page.getByRole('button', { name: 'Gespräch / Wiedervorlage', exact: true }).count(), 0);
      await page.getByRole('button', { name: `Als Favorit merken: ${property.name}` }).click();
      await expect(page.getByRole('button', { name: `Favorit entfernen: ${property.name}` })).toHaveAttribute('aria-pressed', 'true');
    } finally { await readerContext.close(); page = ownerPage; }
  });
  for (const width of [1440, 360, 320]) await step(`Work center keyboard/mobile layout ${width}px`, async () => {
    await page.setViewportSize({ width, height: 1000 }); await page.goto(`${base.origin}/work-center`);
    await expect(page.getByRole('heading', { name: 'Arbeitszentrale', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /Offene Aufgaben:.*gezählte Vorgänge ansehen/ })).toBeVisible();
    await page.keyboard.press('Tab');
    assert.ok(await page.evaluate(() => ['A', 'BUTTON', 'INPUT', 'SELECT'].includes(document.activeElement?.tagName)), 'Keyboard focus should reach a control');
    const layout = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth,
      overflowing: [...document.querySelectorAll('.main-content-body *')].map(element => ({ tag: element.tagName, className: element.className, right: element.getBoundingClientRect().right }))
        .filter(element => element.right > innerWidth + 1).slice(0, 20) }));
    result.layouts ||= []; result.layouts.push(layout);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Horizontal page overflow');
    await page.screenshot({ path: path.join(out, `work-center-${width}.png`), fullPage: false }); result.screenshots.push(`work-center-${width}.png`);
  });
  assert.deepEqual(result.errors, [], 'Unexpected browser errors');
} finally {
  await context?.close(); await api?.dispose(); await browser.close();
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2));
}
