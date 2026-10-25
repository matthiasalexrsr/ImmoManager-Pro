import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
// Reading documents into forms on an owned synthetic server, with the local rules (no AI account): the
// document upload, the invoice receipt, the existing-record question, the marks in the form, the AI
// settings, the HttpOnly session cookie and the Content-Security-Policy.
const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const playwright = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(playwright.href);
const { expect } = await import(new URL('./test.mjs', playwright).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let context, api, page;

const INVOICE = ['Stadtwerke Leipzig GmbH', 'Rechnung Nr. SW-2026-4711', 'Rechnungsdatum: 03.03.2026',
  'Leistungszeitraum: 01.01.2025 - 31.12.2025', 'Wasserversorgung Gohliser Strasse 17', 'Summe netto 1.000,00 EUR',
  'MwSt 7 % 70,00 EUR', 'Gesamtbetrag 1.070,00 EUR', 'zahlbar bis 31.03.2026'];
const LETTER = ['Hausverwaltung Nord GmbH', 'Protokoll der Eigentuemerversammlung', 'Datum: 12.09.2026',
  'Beschluesse zur Dachsanierung und zum Wirtschaftsplan 2027'];

/** A one-page PDF with a text layer, one line per entry. */
function pdf(lines) {
  const text = lines.map(line => `(${line.replace(/[()\\]/g, '')}) Tj T*`).join(' ');
  const content = `BT /F1 11 Tf 14 TL 50 800 Td ${text} ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`];
  let document = '%PDF-1.4\n';
  const offsets = [];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(document)); document += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const start = Buffer.byteLength(document);
  document += `xref\n0 6\n0000000000 65535 f \n${offsets.map(value => `${String(value).padStart(10, '0')} 00000 n \n`).join('')}`
    + `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(document, 'latin1');
}
async function call(method, route, data) {
  const r = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(r.ok(), `${method} ${route}: ${r.status()}`);
  return r.status() === 204 ? null : r.json();
}
async function step(name, run) {
  try { await run(); report.checks.push({ name, ok: true }); }
  catch (error) { report.checks.push({ name, ok: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png') }); throw error; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
const readingStarted = () => page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/ai/readings' && r.request().method() === 'POST');

try {
  const login = await request.newContext({ baseURL: base.origin });
  const response = await login.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok());
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + (await response.json()).access_token } });
  await login.dispose();
  const user = await call('GET', '/auth/me');
  await fs.writeFile(path.join(output, 'invoice.pdf'), pdf(INVOICE));
  await fs.writeFile(path.join(output, 'protokoll.pdf'), pdf(LETTER));
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })); }, user.id);
  page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror', e => report.errors.push(String(e)));
  page.on('console', message => { if (message.type() === 'error' && /Content.Security.Policy/i.test(message.text())) report.errors.push(`CSP: ${message.text()}`); });
  page.on('request', r => { if (/^https?:/.test(r.url()) && new URL(r.url()).origin !== base.origin) report.external.push(r.url()); });

  await step('Sign-in keeps the refresh token in an HttpOnly cookie and out of the page', async () => {
    await page.goto(base.origin + '/login');
    const csp = (await page.request.get(base.origin + '/login')).headers()['content-security-policy'] || '';
    assert.match(csp, /script-src 'self' 'wasm-unsafe-eval'/);
    await page.locator('input[autocomplete="username"]').fill('owner');
    await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
    await page.locator('form button[type="submit"]').click();
    await page.waitForURL(u => u.pathname === '/');
    const cookie = (await context.cookies()).find(item => item.name === 'immo_refresh');
    assert.ok(cookie && cookie.httpOnly && cookie.sameSite === 'Strict' && cookie.path === '/api/v1/auth', 'refresh cookie');
    assert.equal(await page.evaluate(() => localStorage.getItem('refresh_token')), null);
  });

  let firstDocument;
  await step('An uploaded document is read by the local rules, marked in the form and saved after confirmation', async () => {
    await page.goto(base.origin + '/documents');
    const started = readingStarted();
    await page.getByLabel('Dokumentdateien wählen').setInputFiles(path.join(output, 'protokoll.pdf'));
    const reading = page.getByRole('dialog', { name: 'Dokument einlesen' });
    await expect(reading).toBeVisible();
    await expect(reading.getByRole('radio', { name: /Lokale Regeln/ })).toBeChecked();
    const readingId = (await (await started).json()).id;
    await expect(reading.getByRole('table')).toBeVisible();
    await page.screenshot({ path: path.join(output, 'document-reading-1440.png') });
    await reading.getByRole('button', { name: 'In die Maske übernehmen' }).click();
    const form = page.getByRole('dialog', { name: 'Dokument erstellen' });
    await expect(form.getByText(/Werte? von Lokale Regeln/)).toBeVisible();
    await expect(form.getByText(/noch zu bestätigen/)).toBeVisible();
    await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(form.getByText(/prüfen und bestätigen/)).toBeVisible();
    await page.screenshot({ path: path.join(output, 'document-form-marks-1440.png') });
    await form.getByRole('button', { name: 'Alle bestätigen' }).click();
    const saved = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/documents' && r.request().method() === 'POST');
    await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    firstDocument = await (await saved).json();
    await expect(form).toHaveCount(0);
    await expect.poll(async () => (await call('GET', `/ai/readings/${readingId}`)).status).toBe('taken_over');
    assert.equal((await call('GET', `/ai/readings/${readingId}`)).record.id, firstDocument.id);
  });

  await step('The same file again asks about the existing document first', async () => {
    await page.goto(base.origin + '/documents');
    await page.getByLabel('Dokumentdateien wählen').setInputFiles(path.join(output, 'protokoll.pdf'));
    const reading = page.getByRole('dialog', { name: 'Dokument einlesen' });
    const question = reading.getByRole('alertdialog');
    await expect(question).toContainText('gibt es vermutlich schon');
    await expect(question).toContainText('dieselbe Datei');
    await expect(reading.getByRole('button', { name: 'In die Maske übernehmen' })).toBeDisabled();
    await page.screenshot({ path: path.join(output, 'document-duplicate-1440.png') });
    await question.getByRole('button', { name: 'Öffnen' }).first().click();
    await page.waitForURL(u => u.pathname === `/documents/${firstDocument.id}`);
  });

  await step('An invoice receipt is read into the new-invoice form and filed as its document', async () => {
    await page.goto(base.origin + '/invoice-review');
    await page.getByRole('button', { name: 'Rechnung erfassen' }).click();
    const dialog = page.getByRole('dialog', { name: 'Rechnung erfassen' });
    await dialog.getByLabel('Beleg', { exact: true }).setInputFiles(path.join(output, 'invoice.pdf'));
    await dialog.getByRole('button', { name: /Beleg einlesen/ }).click();
    await dialog.getByRole('button', { name: 'In die Rechnung übernehmen' }).click();
    await expect(dialog.getByLabel(/^Rechnungsnr\./, { exact: false }).first()).toHaveValue('SW-2026-4711');
    await expect(dialog.locator('#ir-new-gross_amount')).toHaveValue('1070.00');
    await expect(dialog.locator('#ir-new-cost_category')).toHaveValue('water');           // a cost type of the statement,
    await expect(dialog.locator('#ir-new-cost_category option:checked')).toHaveText('Wasser und Abwasser');   // shown in words
    await dialog.getByRole('button', { name: 'Alle bestätigen' }).click();
    await page.screenshot({ path: path.join(output, 'invoice-reading-1440.png') });
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await page.waitForURL(u => /^\/invoice-review\/[^/]+$/.test(u.pathname));
    const id = decodeURIComponent(new URL(page.url()).pathname.split('/').pop());
    const view = await call('GET', `/invoices/${encodeURIComponent(id)}/review`);
    assert.equal(view.invoice.invoice_number, 'SW-2026-4711');
    assert.ok(view.document?.id, 'the receipt is filed as a document');
  });

  await step('Settings → KI-Verarbeitung explains the reading and stores the personal mode', async () => {
    await page.goto(base.origin + '/settings?section=ai');
    await expect(page.getByRole('heading', { name: 'KI-Verarbeitung', level: 2 })).toBeVisible();
    await expect(page.getByText('nicht verbunden').first()).toBeVisible();
    await expect(page.getByRole('note', { name: 'Datenschutz' })).toContainText('Art. 28');
    const mode = page.getByLabel('Von der KI eingetragene Werte in der Maske');
    await mode.selectOption('mark');
    await page.locator('.setting-card').filter({ has: mode }).getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/ai/readings/options')).confirm_mode).toBe('mark');
    await page.screenshot({ path: path.join(output, 'settings-ai-1440.png'), fullPage: true });
  });

  await step('At 390 px the receipt filed with the invoice is found again, and cancelling closes the reading', async () => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto(base.origin + '/documents');
    await page.getByLabel('Dokumentdateien wählen').setInputFiles(path.join(output, 'invoice.pdf'));
    const reading = page.getByRole('dialog', { name: 'Dokument einlesen' });
    const question = reading.getByRole('alertdialog');
    await expect(question).toContainText('dieselbe Datei · Rechnung');
    await expect(reading.getByRole('button', { name: 'In die Maske übernehmen' })).toBeDisabled();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no sideways scrolling');
    await page.screenshot({ path: path.join(output, 'document-reading-390.png') });
    await question.getByRole('button', { name: 'Abbrechen' }).click();
    await expect(reading).toHaveCount(0);
  });

  assert.deepEqual(report.errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
