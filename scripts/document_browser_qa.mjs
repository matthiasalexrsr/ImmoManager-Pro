// Actual browser and API against the synthetic server owned by the Python runner.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const base = new URL(process.env.QA_BASE_URL || '');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || [8000, 8765].includes(Number(base.port))
  || base.pathname !== '/' || process.env.QA_ALLOW_TEST_WRITES !== '1' || !process.env.QA_PASSWORD) throw new Error('Owned synthetic loopback server required');
const playwrightUrl = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(playwrightUrl.href);
// The core playwright entry point does not export test assertions.
const { expect } = await import(new URL('./test.mjs', playwrightUrl).href);
const output = path.resolve(process.env.QA_OUTPUT);
const fixtures = path.resolve(process.env.QA_FIXTURES);
await fs.mkdir(output, { recursive: true });
const report = { checks: [], screenshots: [], externalRequests: [], pageErrors: [], visualInspection: 'pending_coordinator' };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
let browser, context, api, page;
async function call(method, route, data) {
  const response = await api.fetch(`/api/v1${route}`, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  try { await action(); report.checks.push({ name, passed: true }); }
  catch (error) {
    report.checks.push({ name, passed: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, `failure-${report.checks.length}.png`) }).catch(() => {});
    throw error;
  }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function upload(name, property, contract, unit) {
  const bytes = await fs.readFile(path.join(fixtures, name));
  const response = await api.post('/api/v1/files/upload?folder=documents', { multipart: { file: { name,
    mimeType: name.endsWith('.pdf') ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: bytes } } });
  assert.ok(response.ok(), await response.text());
  const file = await response.json();
  const doc = await call('POST', '/documents', { title: `QA ${name}`, file_url: file.file_url,
    property_id: property.id, contract_id: contract.id, unit_id: unit.id });
  return { doc, bytes };
}
async function openTools(documentId) {
  await page.goto(`${base.origin}/documents?tool_id=${documentId}`);
  const dialog = page.getByRole('dialog', { name: /Dokumentwerkzeuge/ });
  await expect(dialog).toBeVisible();
  return dialog;
}
try {
  api = await request.newContext({ baseURL: base.origin });
  const login = await api.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok());
  const token = (await login.json()).access_token;
  await api.dispose();
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const profile = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Dokumentwerkzeuge' });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Dokumentenhaus', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'QA Wohnung', unit_type: 'residential' });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Dokumentenpartei' });
  const contract = await call('POST', '/contracts', { contract_number: 'QA-DOK-1', property_id: property.id, unit_id: unit.id,
    tenant_id: tenant.id, start_date: '2026-01-01', status: 'active' });
  const docx = await upload('Langdokument.docx', property, contract, unit);
  const pdf = await upload('Werkzeugpruefung.pdf', property, contract, unit);
  browser = await chromium.launch({ headless: true,
    ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', route => {
    const target = new URL(route.request().url());
    if (!['http:', 'https:'].includes(target.protocol) || target.origin === base.origin) return route.continue();
    report.externalRequests.push(target.origin + target.pathname);
    return route.abort('blockedbyclient');
  });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })); }, profile.id);
  page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /Content.Security.Policy/i.test(message.text())) report.pageErrors.push(`CSP: ${message.text()}`); });
  await page.goto(`${base.origin}/login`);
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type=submit]').click();
  await page.waitForURL(url => url.pathname === '/');
  const later = page.getByRole('button', { name: 'Später', exact: true });
  if (await later.isVisible().catch(() => false)) await later.click();
  await step('DOCX original archival through real German UI', async () => {
    const dialog = await openTools(docx.doc.id);
    await dialog.getByRole('button', { name: 'Original jetzt archivieren' }).click();
    await expect(dialog.getByText(/Archivfassung 1/)).toBeVisible();
    const source = await call('GET', `/documents/${docx.doc.id}/work/source`);
    assert.equal(source.sha256, hash(docx.bytes));
  });
  await step('Real local DOCX editor opens long tables, headers, image, comments and tracked changes', async () => {
    const dialog = await openTools(docx.doc.id);
    await dialog.getByRole('button', { name: 'DOCX im lokalen Editor öffnen' }).click();
    await expect(dialog.getByText('Bearbeitung bereit.', { exact: true })).toBeVisible({ timeout: 60000 });
    await expect(dialog.getByLabel('Dokument formatieren und prüfen')).toBeVisible();
    report.docxToolbar = await dialog.getByLabel('Dokument formatieren und prüfen').locator('[role="button"],button').evaluateAll(nodes => nodes.map(node => ({
      label: node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent,
      rect: node.getBoundingClientRect().toJSON(), display: getComputedStyle(node).display,
      parents: [node.parentElement, node.parentElement?.parentElement].filter(Boolean).map(parent => ({
        tag: parent.tagName, class: parent.className, display: getComputedStyle(parent).display,
        width: parent.getBoundingClientRect().width, height: parent.getBoundingClientRect().height,
      })),
    })));
    // Actual native browser input must survive the server save/export path.
    await dialog.locator('.superdoc-fragment').filter({ hasText: 'Prüfdokument:' }).first().click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('Control+Home');
    await page.keyboard.type('QA_BROWSER_AENDERUNG_20261016 ', { delay: 20 });
    await expect(dialog.getByText(/QA_BROWSER_AENDERUNG_20261016/).first()).toBeVisible();
    await dialog.getByRole('button', { name: 'Zwischenstand sichern', exact: true }).click();
    await expect(dialog.getByText('Zwischenstand auf dem Server gesichert.', { exact: true })).toBeVisible({ timeout: 60000 });
    report.toolbarAfterSave = await dialog.getByLabel('Dokument formatieren und prüfen').locator('[role="button"],button').evaluateAll(nodes => nodes.map(node => ({
      label: node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent,
      rect: node.getBoundingClientRect().toJSON(), display: getComputedStyle(node).display,
      visibility: getComputedStyle(node).visibility, opacity: getComputedStyle(node).opacity,
    })));
    await expect(dialog.getByLabel('Dokument formatieren und prüfen').getByRole('button', { name: 'Bold', exact: true })).toBeVisible();
    const boldControl = dialog.getByLabel('Dokument formatieren und prüfen').getByRole('button', { name: 'Bold', exact: true });
    report.boldHit = await boldControl.evaluate(node => {
      const r = node.getBoundingClientRect(); const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return { matched: hit === node || node.contains(hit), actualClass: hit?.className?.baseVal ?? hit?.className };
    });
    assert.ok(report.boldHit.matched, 'Formatting control must receive pointer input after autosave');
    // Exercise the real toolbar, then wait for Vue/browser paint before the
    // visual oracle. DOM geometry alone can precede the toolbar's first paint.
    const activeBefore = await boldControl.locator('.sd-toolbar-button').evaluate(node => node.classList.contains('sd-active'));
    await boldControl.click();
    await expect.poll(() => boldControl.locator('.sd-toolbar-button').evaluate(node => node.classList.contains('sd-active'))).toBe(!activeBefore);
    await boldControl.click();
    await expect.poll(() => boldControl.locator('.sd-toolbar-button').evaluate(node => node.classList.contains('sd-active'))).toBe(activeBefore);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    report.boldPaint = await boldControl.evaluate(node => {
      const details = item => { const c = getComputedStyle(item); return { tag: item.tagName,
        class: typeof item.className === 'string' ? item.className : item.className?.baseVal,
        rect: item.getBoundingClientRect().toJSON(), color: c.color, fill: c.fill, opacity: c.opacity,
        visibility: c.visibility, display: c.display, clipPath: c.clipPath, overflow: c.overflow,
        fontSize: c.fontSize, background: c.backgroundColor, transform: c.transform }; };
      const parents = []; for (let p = node; p; p = p.parentElement) parents.push(details(p));
      return { html: node.outerHTML, parents, children: [...node.querySelectorAll('*')].map(details) };
    });
    const screenshot = path.join(output, 'docx-long-1440.png');
    // The workbench is fixed to the viewport. A full-page capture temporarily
    // resizes the viewport and can catch the native toolbar during refitting.
    await page.screenshot({ path: screenshot }); report.screenshots.push(screenshot);
    await dialog.getByRole('button', { name: 'Neue Fassung speichern', exact: true }).click();
    await expect(dialog.getByText('Neue unveränderliche Fassung gespeichert.', { exact: true })).toBeVisible({ timeout: 60000 });
    const source = await call('GET', `/documents/${docx.doc.id}/work/source`);
    const response = await api.get(`/api/v1/documents/${docx.doc.id}/work/versions/${source.version.id}/download`);
    assert.ok(response.ok());
    await fs.writeFile(path.join(output, 'native-editor-roundtrip.docx'), await response.body());
    assert.equal((await call('GET', `/documents/${docx.doc.id}/work/versions`)).items.at(-1).sha256, hash(docx.bytes));
  });
  await step('PDF annotations retain original bytes and repeated flatten export has one identity', async () => {
    let dialog = await openTools(pdf.doc.id);
    await dialog.getByRole('button', { name: 'Original jetzt archivieren' }).click();
    await expect(dialog.getByText(/Archivfassung 1/)).toBeVisible();
    await dialog.getByRole('button', { name: 'Anmerkungen beginnen' }).click();
    await expect(dialog.getByRole('button', { name: 'Bereich übernehmen' })).toBeEnabled();
    await dialog.getByLabel('Bereich per Tastatur: Seite; links; oben; rechts; unten; Rotation').fill('1;20;30;250;80;0');
    await dialog.getByRole('button', { name: 'Bereich übernehmen' }).click();
    await dialog.getByRole('button', { name: 'Anmerkungsebene speichern' }).click();
    await expect.poll(async () => (await call('GET', `/documents/${pdf.doc.id}/work/source`)).layer_revision,
      { timeout: 60000 }).toBe(1);
    assert.equal((await call('GET', `/documents/${pdf.doc.id}/work/source`)).sha256, hash(pdf.bytes));
    await dialog.getByLabel('Ausgabewerkzeug', { exact: true }).selectOption('flatten');
    await dialog.getByRole('button', { name: 'Ausgabeauftrag anlegen' }).click();
    await dialog.getByRole('button', { name: 'Verarbeiten / fortsetzen' }).click();
    await expect(dialog.getByRole('button', { name: /Ausgabe herunterladen/ })).toBeVisible({ timeout: 60000 });
  });
  for (const width of [1440, 360, 320]) await step(`PDF tools responsive, keyboard and screenshot ${width}`, async () => {
    await page.setViewportSize({ width, height: 1000 });
    const dialog = await openTools(pdf.doc.id);
    await expect(dialog.locator('.pdf-preview-canvas[role="img"]')).toBeVisible({ timeout: 60000 });
    await expect(dialog.getByText('Anmerkungen', { exact: true })).toBeVisible();
    report.layout ??= {};
    report.layout[width] = await dialog.evaluate(node => ({ client: node.clientWidth, scroll: node.scrollWidth,
      overflow: [...node.querySelectorAll('*')].filter(child => child.getBoundingClientRect().right > node.getBoundingClientRect().right + 1)
        .slice(0, 12).map(child => ({ tag: child.tagName, class: typeof child.className === 'string' ? child.className : '',
          text: child.textContent.slice(0, 100), right: child.getBoundingClientRect().right })) }));
    assert.ok(report.layout[width].scroll <= report.layout[width].client + 1, 'Dialog horizontal overflow');
    const screenshot = path.join(output, `pdf-tools-${width}.png`);
    await page.screenshot({ path: screenshot }); report.screenshots.push(screenshot);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });
  await step('Optional component uses no external service', async () => assert.deepEqual(report.externalRequests, []));
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await browser?.close(); await api?.dispose();
}
