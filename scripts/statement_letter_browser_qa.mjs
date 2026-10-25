/** Full billing correspondence on an owned synthetic server; no mocked approval. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], screenshots: [], geometry: [], page_errors: [], external: [] };
let api, browser, context, page;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function step(name, action) {
  try { await action(); report.checks.push({ name, passed: true }); }
  catch (error) { report.checks.push({ name, passed: false, error: String(error) }); await page?.screenshot({ path: path.join(output, `failure-${report.checks.length}.png`) }).catch(() => {}); throw error; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function post(endpoint, data) {
  const response = await api.post('/api/v1' + endpoint, { data });
  assert.ok(response.ok(), endpoint + ': ' + await response.text()); return response.json();
}
try {
  api = await request.newContext({ baseURL: base.origin });
  const login = await api.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok(), await login.text()); const token = (await login.json()).access_token;
  await api.dispose(); api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const profile = await (await api.get('/api/v1/auth/me')).json();
  const portfolio = await post('/portfolios', { name: 'Brief QA Bestand', owner_name: 'Zoë Łukasz Verwaltung' });
  const property = await post('/properties', { portfolio_id: portfolio.id, name: 'Brief QA Haus', property_type: 'residential', address_line: 'Prießnitzstraße 4', postal_code: '01099', city: 'Dresden' });
  const unit = await post('/units', { property_id: property.id, label: 'Brief QA Wohnung', unit_type: 'flat', area_sqm: 72 });
  const tenant = await post('/tenants', { full_name: 'Zoë Łukasz Иван Μαρία', address_line: 'Neue Straße 15', postal_code: '01097', city: 'Dresden' });
  await post('/contracts', { contract_number: 'BRIEF-QA-2025', property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2024-01-01' });
  const period = await post('/billing/periods', { property_id: property.id, label: 'Brief QA 2025', start_date: '2025-01-01', end_date: '2025-12-31' });
  const key = await post('/billing/allocation-keys', { property_id: property.id, name: 'Einheiten', key_type: 'unit_count' });
  for (let index = 1; index <= 72; index++) await post('/billing/cost-items', { billing_period_id: period.id, description: `Kostenposition ${index} – Prüfung & Verteilung <2025> Straße, Müll und Gebäude`, amount: 12.34 + index, allocation_key_id: key.id });
  const statements = await post(`/billing/periods/${period.id}/generate`, {});
  const statement = statements.find(row => row.party !== 'vacancy'); assert.ok(statement);
  const statementBase = `/billing/statements/${statement.id}`;
  const address = 'Prießnitzstraße 15, Aufgang Süd – z. Hd. Zoë Łukasz\nAbteilung Gebäudebetrieb und Betriebskosten\nHinterhaus, vierte Etage, rechte Tür\n01097 Dresden, Deutschland';
  await step('Real draft PDF is marked and cannot create an original', async () => {
    const source = await (await api.get('/api/v1' + statementBase + '/letter-context')).json(); assert.equal(source.can_publish, false);
    const payload = { source_revision: source.source_revision, data: { ...source.defaults, sender_name: 'Zoë Łukasz Verwaltung', sender_address: address, recipient_address: address } };
    const shown = await post(statementBase + '/letter-preview', payload); assert.equal(shown.review.draft, true);
    const pdf = await api.post('/api/v1' + statementBase + '/letter-preview-pdf', { data: payload }); assert.ok(pdf.ok());
    const bytes = await pdf.body(); assert.equal(sha(bytes), shown.pdf_sha256); await fs.writeFile(path.join(output, 'draft-letter.pdf'), bytes);
    const denied = await api.post('/api/v1' + statementBase + '/letter-publish', { data: { ...payload, review_hash: shown.review_hash, idempotency_key: 'native-draft-denied' } }); assert.equal(denied.status(), 409);
  });
  await post(`/billing/periods/${period.id}/finalize`, {});
  const legacy = await api.get('/api/v1' + statementBase + '/pdf'); assert.ok(legacy.ok()); const legacyHash = sha(await legacy.body());
  browser = await chromium.launch({ headless: true, ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
  await context.route('**/*', route => { const url = new URL(route.request().url()); if (!['http:', 'https:'].includes(url.protocol) || url.origin === base.origin) return route.continue(); report.external.push(url.origin + url.pathname); return route.abort('blockedbyclient'); });
  await context.addInitScript(({ token, id }) => { localStorage.setItem('access_token', token); localStorage.setItem('locale', 'de-DE'); localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })); }, { token, id: profile.id });
  page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /Content.Security.Policy/i.test(message.text())) report.page_errors.push(`CSP: ${message.text()}`); });
  await step('Open letter from actual Statements list and review real multi-page Unicode PDF', async () => {
    await page.goto(`${base.origin}/statements?filter=statements&focus_id=${statement.id}`);
    await page.getByRole('button', { name: 'Anschreiben & PDF', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Abrechnungsbrief', exact: true }); await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Absender *', { exact: true })).toBeEnabled();
    await dialog.getByLabel('Absender *', { exact: true }).fill('Zoë Łukasz Verwaltung');
    await dialog.getByLabel('Absenderanschrift *', { exact: true }).fill(address);
    await dialog.getByLabel('Empfängeranschrift *', { exact: true }).fill(address);
    await dialog.getByLabel('Einleitung', { exact: true }).fill('Guten Tag, anbei erhalten Sie die geprüfte Betriebskostenabrechnung. Straße, Gebäude und Müllabfuhr wurden vollständig berücksichtigt.\n\n' + 'Bitte prüfen Sie alle Kostenpositionen und die Verteilung. '.repeat(12));
    await dialog.getByRole('button', { name: 'PDF-Vorschau erstellen', exact: true }).click();
    await expect(dialog.getByRole('img', { name: /Abrechnungsbrief.*Seite 1 von/ })).toBeVisible({ timeout: 30000 });
    const count = await dialog.locator('.pdf-preview-page-count').innerText(); report.page_count = Number(count.match(/\d+/)[0]); assert.ok(report.page_count >= 3);
    await dialog.getByRole('button', { name: 'PDF-Text', exact: true }).click();
    await expect(dialog.locator('.pdf-preview-text')).toContainText('Zoë Łukasz');
    await dialog.getByRole('button', { name: 'PDF-Text', exact: true }).click();
  });
  const dialog = page.getByRole('dialog', { name: 'Abrechnungsbrief', exact: true });
  for (const width of [1440, 360, 320]) await step(`Letter dialog, fields, PDF toolbar and actions remain unclipped at ${width}px`, async () => {
    await page.setViewportSize({ width, height: width === 1440 ? 1100 : 1000 });
    await expect.poll(() => dialog.locator('.pdf-preview-toolbar').locator('button,input').first().evaluate(node => Math.round(node.getBoundingClientRect().height))).toBeGreaterThanOrEqual(width <= 640 ? 44 : 32);
    const geometry = await dialog.evaluate(node => {
      const bounds = node.getBoundingClientRect();
      const clipped = [...node.querySelectorAll('button,input,textarea,select')].map(element => ({ name: element.getAttribute('aria-label') || element.id || element.textContent, rect: element.getBoundingClientRect() })).filter(({ rect }) => rect.width && (rect.left < bounds.left - 1 || rect.right > bounds.right + 1)).map(({ name }) => name);
      return { width: bounds.width, x: bounds.x, right: bounds.right, viewport: innerWidth, clipped, scroll: node.querySelector('.statement-letter-body').scrollWidth, client: node.querySelector('.statement-letter-body').clientWidth };
    });
    report.geometry.push({ width, ...geometry }); assert.deepEqual(geometry.clipped, []); assert.ok(geometry.x >= 0 && geometry.right <= width); assert.ok(geometry.scroll <= geometry.client + 1);
    await dialog.locator('.statement-letter-body').evaluate(node => { node.scrollTop = 0; });
    const top = path.join(output, `letter-fields-${width}.png`); await page.screenshot({ path: top }); report.screenshots.push(top);
    await dialog.locator('.statement-letter-preview').scrollIntoViewIfNeeded();
    const pdf = path.join(output, `letter-preview-${width}.png`); await page.screenshot({ path: pdf }); report.screenshots.push(pdf);
  });
  let command, firstSaved;
  await step('Lost real publish success holds inputs and repeats the identical command once', async () => {
    let attempts = 0;
    await page.route('**/letter-publish', async route => {
      attempts++;
      if (attempts === 1) { command = route.request().postDataJSON(); const response = await route.fetch(); assert.equal(response.status(), 201); firstSaved = await response.json(); await route.abort('failed'); }
      else { assert.deepEqual(route.request().postDataJSON(), command); await route.continue(); }
    });
    await dialog.getByRole('checkbox').check(); await dialog.getByRole('button', { name: 'Als Original archivieren', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Archivierung erneut prüfen' })).toBeEnabled();
    await expect(dialog.getByLabel('Betreff *', { exact: true })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Briefdialog schließen', exact: true }).click(); await expect(dialog).toBeVisible();
    const before = await (await api.get('/api/v1' + statementBase + '/letter-context')).json(); assert.equal(before.originals.length, 1);
    await dialog.getByRole('button', { name: 'Archivierung erneut prüfen' }).click();
    await expect(dialog.getByText('Das Original wurde archiviert.', { exact: false })).toBeVisible(); assert.equal(attempts, 2);
    const after = await (await api.get('/api/v1' + statementBase + '/letter-context')).json(); assert.equal(after.originals.length, 1); assert.equal(after.originals[0].document_id, firstSaved.document_id);
    report.original = firstSaved;
  });
  await step('Protected original download matches review, prior PDF stays unchanged and history survives reopening', async () => {
    const download = page.waitForEvent('download'); await dialog.getByRole('button', { name: 'Original herunterladen', exact: true }).click();
    const downloaded = await download; const destination = path.join(output, 'archived-letter.pdf'); await downloaded.saveAs(destination);
    assert.equal(sha(await fs.readFile(destination)), firstSaved.pdf_sha256);
    const legacyAfter = await api.get('/api/v1' + statementBase + '/pdf'); assert.equal(sha(await legacyAfter.body()), legacyHash);
    await dialog.getByRole('button', { name: 'Schließen', exact: true }).click(); await expect(dialog).toBeHidden();
    await page.getByRole('button', { name: 'Anschreiben & PDF', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Original herunterladen', exact: true })).toBeEnabled();
    await expect(dialog.getByRole('link', { name: 'Dokument öffnen', exact: true })).toHaveAttribute('href', `/documents/${firstSaved.document_id}`);
  });
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external, []);
} finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); await context?.close(); await browser?.close(); await api?.dispose(); }
