/** Genuine local answers on an owned synthetic installation; no provider login. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect: baseExpect } = await import(new URL('./test.mjs', module).href);
const expect = baseExpect.configure({ timeout: 30000 });
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const fixture = JSON.parse(await fs.readFile(process.env.QA_ASSISTANT_FIXTURE, 'utf8'));
assert.equal(fixture.synthetic_only, true);
const report = { synthetic_only: true, provider_login_started: false, genuine_local_answers: true, manual_note_fixture: true, checks: [], page_errors: [], external: [] };
const browser = await chromium.launch({ headless: true, ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let context, page, api;
async function step(name, action) {
  try { await action(); report.checks.push({ name, ok: true }); }
  catch (error) { report.checks.push({ name, ok: false, error: String(error) }); await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); throw error; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function call(method, route, data) { const response = await api.fetch('/api/v1' + route, { method, data }); assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`); return response.status() === 204 ? null : response.json(); }
async function fits() { const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth })); assert.ok(size.document <= size.viewport + 1, 'Horizontal overflow: ' + JSON.stringify(size)); }
function syntheticPdf() {
  const content = number => `BT /F1 24 Tf 72 730 Td (Synthetischer Browser-Beleg - Seite ${number}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', ...[1, 2].map(number => `<< /Length ${content(number).length} >>\nstream\n${content(number)}\nendstream`)];
  let result = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(result)); result += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const start = Buffer.byteLength(result); result += `xref\n0 8\n0000000000 65535 f \n${offsets.slice(1).map(offset => String(offset).padStart(10, '0') + ' 00000 n ').join('\n')}\ntrailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(result);
}
try {
  const bootstrap = await request.newContext({ baseURL: base.origin });
  const response = await bootstrap.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } }); assert.ok(response.ok());
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + (await response.json()).access_token } }); await bootstrap.dispose();
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })); }, fixture.actor_id);
  page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror', error => report.page_errors.push(String(error)));
  page.on('request', req => { if (/^https?:/.test(req.url()) && new URL(req.url()).origin !== base.origin) report.external.push(req.url()); if (/\/assistant\/connections\/[^/]+\/login/.test(req.url())) throw Error('Provider login forbidden in this harness'); });
  await page.goto(base.origin + '/login'); await page.locator('input[autocomplete="username"]').fill('owner'); await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD); await page.locator('form button[type="submit"]').click(); await page.waitForURL(url => url.pathname === '/');
  let conversationId;
  await step('New local chat, genuine attachment upload, image preview and keyboard close', async () => {
    await page.goto(base.origin + '/assistant'); await expect(page.getByText('Lokal verfügbar', { exact: true })).toBeVisible();
    const png = Buffer.from(await page.evaluate(() => { const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32; const brush = canvas.getContext('2d'); brush.fillStyle = '#176c59'; brush.fillRect(0, 0, 32, 32); return canvas.toDataURL('image/png').split(',')[1]; }), 'base64');
    await page.locator('input[type="file"]').setInputFiles([{ name: 'Browser-Beleg.txt', mimeType: 'text/plain', buffer: Buffer.from('Rechnung Browser-Test\nRechnungsnr. QA-18\nGesamtbetrag: 123,45 EUR\nDatum: 18.10.2026') }, { name: 'Browser-Bild.png', mimeType: 'image/png', buffer: png }, { name: 'Browser-Beleg.pdf', mimeType: 'application/pdf', buffer: syntheticPdf() }]);
    await page.waitForURL(url => Boolean(url.searchParams.get('conversation'))); conversationId = new URL(page.url()).searchParams.get('conversation');
    const selection = page.getByRole('group', { name: 'Dateiauswahl für die Nachricht' });
    const opener = selection.getByRole('button', { name: 'Datei ansehen: Browser-Bild.png', exact: true }); await opener.click();
    const dialog = page.getByRole('dialog', { name: 'Browser-Bild.png', exact: true }); await expect(dialog.getByRole('img', { name: 'Browser-Bild.png', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'assistant-image-1440.png') }); await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
    await selection.getByRole('button', { name: 'Datei ansehen: Browser-Beleg.pdf', exact: true }).click();
    const pdf = page.getByRole('dialog', { name: 'Browser-Beleg.pdf', exact: true }); await expect(pdf.getByRole('img', { name: /Seite 1 von 2/ })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'assistant-pdf-page1-1440.png') }); await pdf.getByRole('button', { name: 'Nächste Seite', exact: true }).click(); await expect(pdf.getByRole('img', { name: /Seite 2 von 2/ })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'assistant-pdf-page2-1440.png') }); await page.keyboard.press('Escape'); await expect(pdf).toHaveCount(0);
    await page.getByLabel('Ihre Nachricht', { exact: true }).fill('Fasse die hochgeladenen Unterlagen lokal zusammen und nenne fehlende Angaben.'); await page.getByRole('button', { name: 'Lokal analysieren', exact: true }).click();
    await expect(page.locator('.assistant-run').getByText('Abgeschlossen', { exact: true })).toBeVisible();
    const messages = await call('GET', `/assistant/conversations/${conversationId}/messages`); assert.equal(messages.items.filter(item => item.role === 'assistant').length, 1); assert.ok(messages.items.find(item => item.role === 'assistant').content.length > 20);
    const runs = await call('GET', `/assistant/conversations/${conversationId}/runs`); assert.equal(runs.items[0].state, 'completed'); assert.equal(runs.items[0].web_research, false); report.local_run_id = runs.items[0].id;
    await page.reload(); await expect(page.locator('.assistant-run').getByText('Abgeschlossen', { exact: true })).toBeVisible(); await expect(page.getByRole('article')).toHaveCount(2);
    await page.screenshot({ path: path.join(output, 'assistant-local-answer-1440.png'), fullPage: true });
  });
  await step('Exact record context, deterministic local report and report-bound answer', async () => {
    await page.getByRole('button', { name: 'Akte hinzufügen', exact: true }).click(); await page.getByLabel('Akten durchsuchen', { exact: true }).fill(fixture.property.name); await page.getByRole('button', { name: 'Akten suchen', exact: true }).click();
    await page.getByRole('button', { name: 'Hinzufügen', exact: true }).first().click();
    await expect(page.getByRole('link', { name: 'Akte öffnen →', exact: true })).toHaveAttribute('href', '/properties/' + fixture.property.id);
    await page.getByRole('checkbox', { name: 'Lokale Auswertung mitsenden', exact: true }).check();
    await page.getByLabel('Berichtsstichtag', { exact: true }).fill('2026-10-18'); await page.getByLabel('Berichtszeitraum von', { exact: true }).fill('2026-10-01'); await page.getByLabel('Berichtszeitraum bis', { exact: true }).fill('2026-10-18');
    await page.getByRole('button', { name: 'Ausgewählte Quellen lokal prüfen', exact: true }).click();
    const proof = page.getByRole('region', { name: 'Lokaler Berechnungsnachweis', exact: true }); await expect(proof).toContainText('123,45');
    const original = proof.getByRole('link', { name: 'Originalauswertung mit diesen Filtern öffnen →', exact: true }); assert.equal(new URL(await original.getAttribute('href'), base.origin).searchParams.get('property_id'), fixture.property.id);
    await page.getByLabel('Ihre Nachricht', { exact: true }).fill('Erläutere die geprüfte lokale Zahlungsübersicht.'); await page.getByLabel('Ihre Nachricht', { exact: true }).press('Control+Enter');
    await expect(page.locator('.assistant-run').getByText('Abgeschlossen', { exact: true })).toBeVisible(); await expect(page.getByRole('article')).toHaveCount(4); await expect(page.getByRole('table', { name: 'Tabelle aus der Antwort', exact: true }).first()).toBeVisible();
    const runs = await call('GET', `/assistant/conversations/${conversationId}/runs`); assert.equal(runs.items[0].report.property_id, fixture.property.id); assert.equal(runs.items[0].financial_summary.totals.income, '123.45'); assert.ok(runs.items[0].financial_summary.result_hash);
    await page.screenshot({ path: path.join(output, 'assistant-report-1440.png'), fullPage: true });
  });
  await step('Private title, archive, reload and restoration', async () => {
    await page.getByText('Chat verwalten', { exact: true }).click(); await page.getByLabel('Chattitel', { exact: true }).fill('Browser geprüfter KI-Verlauf'); await page.getByRole('button', { name: 'Titel speichern', exact: true }).click(); await expect(page.getByRole('heading', { name: 'Browser geprüfter KI-Verlauf', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Chat archivieren', exact: true }).click(); await expect(page.getByLabel('Ihre Nachricht', { exact: true })).toBeDisabled(); await page.reload(); await expect(page.getByLabel('Ihre Nachricht', { exact: true })).toBeDisabled();
    await expect(page.getByRole('heading', { name: 'Browser geprüfter KI-Verlauf', exact: true })).toBeVisible();
    const reconcile = page.getByRole('button', { name: 'Chatänderung abgleichen', exact: true });
    if (await reconcile.isVisible()) { report.archive_reconciliation = true; await reconcile.click(); await expect(reconcile).toHaveCount(0); }
    await expect(page.getByText(/Dieser Chat ist archiviert/)).toBeVisible();
    await page.getByText('Chat verwalten', { exact: true }).click(); await page.getByRole('button', { name: 'Aus Archiv zurückholen', exact: true }).click(); await expect(page.getByLabel('Ihre Nachricht', { exact: true })).toBeEnabled();
  });
  await step('Explicit manual note fixture, reviewed draft and existing note form', async () => {
    await page.goto(base.origin + '/assistant?conversation=' + fixture.conversation.id);
    await page.getByRole('button', { name: 'Angaben und Quellen prüfen', exact: true }).click(); await page.getByRole('checkbox', { name: 'Ich habe die Angaben und ihre Quellen geprüft.', exact: true }).check(); await page.getByRole('button', { name: 'Entwurf übernehmen', exact: true }).click();
    await page.getByRole('button', { name: 'Entwurf im Fachformular öffnen', exact: true }).click(); const dialog = page.getByRole('dialog'); await expect(dialog.getByLabel('Gesprächsnotiz *', { exact: true })).toHaveValue('Manueller synthetischer Prüfentwurf für die Browserabnahme.');
    await page.screenshot({ path: path.join(output, 'assistant-note-draft-1440.png') }); await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await expect(page.getByText('Die Notiz wurde im bestehenden Fachablauf gespeichert.', { exact: true })).toBeVisible();
  });
  await step('Provider status only, explicit web option and local reports remain usable', async () => {
    await page.getByRole('button', { name: 'Neuer Chat', exact: true }).click(); await page.getByLabel('Assistent auswählen', { exact: true }).selectOption('codex');
    await expect(page.getByRole('button', { name: 'Senden', exact: true })).toBeDisabled(); await expect(page.getByRole('checkbox', { name: /Internetrecherche zulassen/ })).not.toBeChecked();
    await page.screenshot({ path: path.join(output, 'assistant-provider-status-1440.png') }); await page.getByLabel('Assistent auswählen', { exact: true }).selectOption('local'); await expect(page.getByText('Lokal verfügbar', { exact: true })).toBeVisible();
  });
  await step('1440, 360 and 320 pixel layouts and keyboard-accessible composer', async () => {
    await page.goto(base.origin + '/assistant?conversation=' + conversationId); await expect(page.getByLabel('Ihre Nachricht', { exact: true })).toBeEnabled();
    for (const width of [1440, 360, 320]) { await page.setViewportSize({ width, height: 1000 }); await fits(); await page.getByLabel('Ihre Nachricht', { exact: true }).focus(); await expect(page.getByLabel('Ihre Nachricht', { exact: true })).toBeFocused(); await page.screenshot({ path: path.join(output, `assistant-${width}.png`), fullPage: true }); }
    await page.getByRole('button', { name: 'Chats', exact: true }).click(); await expect(page.getByRole('button', { name: /Browser geprüfter KI-Verlauf/ })).toBeVisible(); await fits(); await page.screenshot({ path: path.join(output, 'assistant-chats-320.png'), fullPage: true });
  });
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); await api?.dispose(); await context?.close(); await browser.close();
}
