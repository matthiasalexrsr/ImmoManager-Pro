// Real browser acceptance checks against an isolated local QA server.
// Run from the repository root. Required QA_PASSWORD, QA_BASE_URL (loopback only),
// and QA_ALLOW_TEST_WRITES=1. Optional QA_OWNER, QA_READONLY, QA_PLAYWRIGHT_PATH.
// Use QA_PLAYWRIGHT_PATH for an existing @playwright/test/index.mjs installation;
// otherwise the package is resolved from frontend/package.json.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const password = process.env.QA_PASSWORD;
if (!password) throw new Error('Set QA_PASSWORD to the disposable local QA account password.');
if (process.env.QA_ALLOW_TEST_WRITES !== '1') throw new Error('Set QA_ALLOW_TEST_WRITES=1 only for an isolated QA server; this script creates and deletes disposable records.');
if (!process.env.QA_BASE_URL) throw new Error('Set QA_BASE_URL to the isolated local QA server URL.');
const server = new URL(process.env.QA_BASE_URL);
if (!['http:', 'https:'].includes(server.protocol) || !['localhost', '127.0.0.1', '[::1]'].includes(server.hostname) || server.username || server.password) throw new Error('QA_BASE_URL must use HTTP(S) on a loopback host, without URL credentials.');
if (server.pathname !== '/' || server.search || server.hash) throw new Error('QA_BASE_URL must be a server origin, without a path, query or fragment.');
const base = server.origin;
await fs.access(path.join(process.cwd(), 'frontend', 'package.json'));
const resolveFrontend = createRequire(path.join(process.cwd(), 'frontend', 'package.json'));
let playwrightPath = process.env.QA_PLAYWRIGHT_PATH;
if (playwrightPath && !path.isAbsolute(playwrightPath)) throw new Error('QA_PLAYWRIGHT_PATH must be an absolute module path.');
if (!playwrightPath) {
  try { playwrightPath = resolveFrontend.resolve('@playwright/test'); }
  catch { throw new Error('Set QA_PLAYWRIGHT_PATH to an existing @playwright/test/index.mjs installation, or install Playwright in your own frontend development environment.'); }
}
const { chromium, expect, request } = await import(pathToFileURL(playwrightPath).href);
const output = path.resolve(process.cwd(), 'artifacts', 'party-browser');
const marker = `QA-Party-${new Date().toISOString().replace(/[:.]/g, '-')}`;
const results = { marker, base, started: new Date().toISOString(), checks: [], screenshots: [], consoleErrors: [], apiFailures: [], cleanup: [], fixtures: {} };
const entities = [];
let api;
let owner;
let readonly;
// Use full Chromium's new headless mode: the lightweight headless shell does
// not initialize native PDF viewer frames reliably.
const browser = await chromium.launch({ channel: 'chromium', headless: true, timeout: 15000 });

async function bounded(promise, milliseconds, label) {
  let timeout;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timeout = setTimeout(() => { const error = new Error(`${label} exceeded ${milliseconds}ms`); error.code = 'QA_PROTOCOL_TIMEOUT'; reject(error); }, milliseconds);
    })]);
  } finally { clearTimeout(timeout); }
}

function pdf(text) {
  const content = `BT /F1 18 Tf 50 750 Td (${text.replace(/[()\\]/g, '')}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
  ];
  let document = '%PDF-1.4\n';
  const offsets = [0];
  for (let i = 0; i < objects.length; i++) {
    offsets.push(Buffer.byteLength(document));
    document += `${i + 1} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const start = Buffer.byteLength(document);
  document += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(value => `${String(value).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(document);
}

async function step(name, fn) {
  const began = Date.now();
  try {
    const detail = await bounded(fn(), 30000, name);
    results.checks.push({ name, status: 'pass', milliseconds: Date.now() - began, detail });
    console.log(`PASS ${name}`);
    return true;
  } catch (error) {
    results.checks.push({ name, status: 'fail', milliseconds: Date.now() - began, error: error.message });
    console.log(`FAIL ${name}: ${error.message.split('\n')[0]}`);
    if (error.code === 'QA_PROTOCOL_TIMEOUT') throw error;
    if (owner) await bounded(owner.screenshot({ path: path.join(output, `failure-${results.checks.length}.png`), fullPage: true, timeout: 3000 }), 3500, 'failure screenshot').catch(() => {});
    return false;
  } finally {
    await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  }
}

async function call(method, route, data) {
  const response = await api.fetch(`/api/v1${route}`, { method, data, timeout: 15000 });
  if (!response.ok()) throw new Error(`${method} ${route}: HTTP ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}

async function create(collection, data) {
  const value = await call('POST', `/${collection}`, data);
  entities.push({ collection, id: value.id });
  return value;
}

function observe(page) {
  page.setDefaultTimeout(10000);
  page.setDefaultNavigationTimeout(15000);
  page.on('pageerror', error => results.consoleErrors.push(error.message));
  page.on('response', async response => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/api/') && response.status() >= 400) results.apiFailures.push({ path: url.pathname, status: response.status() });
    if (url.pathname === '/api/v1/documents' || url.pathname === '/api/v1/documents/import') {
      if (response.request().method() === 'POST' && response.status() === 201) {
        const value = await response.json().catch(() => null);
        if (value?.id) entities.push({ collection: 'documents', id: value.id });
      }
    }
  });
}

async function loginUI(page, username) {
  await page.goto(`${base}/login`);
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');
  const offer = page.getByRole('button', { name: 'Später', exact: true });
  if (await offer.isVisible().catch(() => false)) await offer.click();
  // The tour preference is per QA browser context, never changes server data.
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage).filter(key => key.startsWith('immo.tutorial.'))) localStorage.setItem(key, JSON.stringify({ offered: true }));
  });
}

async function gotoDocuments(page, tenantId) {
  await page.goto(`${base}/documents?tenant_id=${encodeURIComponent(tenantId)}`);
  await expect(page.getByLabel('Mieter / Partei', { exact: true })).toHaveValue(tenantId);
  await expect(page.getByRole('heading', { level: 1, name: 'Dokumente' })).toBeVisible();
  const offer = page.getByRole('button', { name: 'Später', exact: true });
  if (await offer.isVisible().catch(() => false)) await offer.click();
}

async function screenshot(page, filename, scope = 'page') {
  const dimensions = await page.evaluate(() => {
    const panel = document.querySelector('.party-panel');
    const scroller = panel?.querySelector('.party-panel-content');
    return { viewport: { width: innerWidth, height: innerHeight }, root: { width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }, panel: panel && { width: panel.clientWidth, scrollWidth: panel.scrollWidth }, content: scroller && { width: scroller.clientWidth, scrollWidth: scroller.scrollWidth } };
  });
  // Wait only for finite animations in this top document; never ask native PDF
  // guest frames to execute animation scripts.
  await bounded(page.evaluate(async () => {
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
  }), 3000, 'finite page animations');
  await bounded(page.screenshot({ path: path.join(output, filename), fullPage: scope === 'documents page', timeout: 10000 }), 11000, 'browser screenshot');
  results.screenshots.push({ filename, scope, dimensions });
  if (!dimensions.panel) assert.ok(dimensions.root.scrollWidth <= dimensions.root.width + 1, `Root overflows horizontally: ${JSON.stringify(dimensions)}`);
  if (dimensions.panel) assert.ok(dimensions.panel.scrollWidth <= dimensions.panel.width + 1, `Panel overflows: ${JSON.stringify(dimensions)}`);
  if (dimensions.content) assert.ok(dimensions.content.scrollWidth <= dimensions.content.width + 1, `Panel content overflows: ${JSON.stringify(dimensions)}`);
  return dimensions;
}

try {
  await fs.mkdir(output, { recursive: true });
  const setup = await request.newContext({ baseURL: base, timeout: 15000 });
  const response = await setup.post('/api/v1/auth/login', { data: { username: process.env.QA_OWNER || 'mat.thias', password } });
  assert.equal(response.status(), 200, 'QA owner API login failed');
  const credentials = await response.json();
  api = await request.newContext({ baseURL: base, extraHTTPHeaders: { Authorization: `Bearer ${credentials.access_token}` }, timeout: 15000 });
  const ownerProfile = await call('GET', '/auth/me');
  await setup.dispose();
  await fs.mkdir(output, { recursive: true });
  const pdfBuffer = pdf(`${marker} historical lease document`);
  await fs.writeFile(path.join(output, 'qa-lease.pdf'), pdfBuffer);
  await fs.writeFile(path.join(output, 'qa-single.pdf'), pdf('Disposable QA single upload'));
  await fs.writeFile(path.join(output, 'qa-batch-a.pdf'), pdf('Disposable QA batch A upload'));
  await fs.writeFile(path.join(output, 'qa-batch-b.pdf'), pdf('Disposable QA batch B upload'));
  const portfolio = await create('portfolios', { name: `${marker} portfolio` });
  const property = await create('properties', { portfolio_id: portfolio.id, name: `${marker} Lindenhof`, property_type: 'residential', address_line: 'QA Lindenstraße 8', city: 'Berlin' });
  const unit = await create('units', { property_id: property.id, label: 'QA 2. OG links', unit_type: 'apartment', cold_rent: 800, service_charge_advance: 100, heating_advance: 60 });
  const historicUnit = await create('units', { property_id: property.id, label: 'QA EG historisch', unit_type: 'apartment', cold_rent: 550, service_charge_advance: 80, heating_advance: 40 });
  const tenant = await create('tenants', { full_name: `${marker} Anna Müller`, email: 'qa-anna@example.test', phone: '+49 30 1234567', address_line: 'QA Lindenstraße 8', postal_code: '10115', city: 'Berlin', country: 'DE', notes: 'Disposable browser acceptance fixture.' });
  const direct = await create('tenants', { full_name: `${marker} Direkt Ohne Vertrag`, email: 'qa-direct@example.test' });
  const contract = await create('contracts', { contract_number: `${marker}-CURRENT`, property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, status: 'active', start_date: '2024-01-01' });
  const history = await create('contracts', { contract_number: `${marker}-HISTORY`, property_id: property.id, unit_id: historicUnit.id, tenant_id: tenant.id, status: 'terminated', start_date: '2020-01-01', end_date: '2023-12-31' });
  const upload = await api.post('/api/v1/files/upload?folder=documents', { multipart: { file: { name: 'qa-lease.pdf', mimeType: 'application/pdf', buffer: pdfBuffer } } });
  assert.equal(upload.status(), 200, `PDF upload failed: ${await upload.text()}`);
  const stored = await upload.json();
  const historicalDoc = await create('documents', { title: `${marker} Historischer Mietvertrag`, document_type: 'Mietvertrag', document_date: '2020-01-01', description: 'Vertrag aus dem früheren Mietverhältnis', contract_id: history.id, file_url: stored.file_url });
  await create('documents', { title: `${marker} Aktuelles Protokoll`, document_type: 'Protokoll', contract_id: contract.id, file_url: stored.file_url });
  await create('documents', { title: `${marker} Direkter Brief`, document_type: 'Brief', tenant_id: tenant.id, file_url: stored.file_url });
  await create('documents', { title: `${marker} Fremdes Einheitendokument`, document_type: 'Sonstiges', unit_id: unit.id, file_url: stored.file_url });
  for (let i = 0; i < 26; i++) await create('documents', { title: `${marker} Direkt ${String(i + 1).padStart(2, '0')}`, document_type: i % 2 ? 'Brief' : 'Protokoll', tenant_id: direct.id, document_date: '2025-01-01', file_url: stored.file_url });
  results.fixtures = { tenant: tenant.id, directTenant: direct.id, historicalDocument: historicalDoc.id, contract: contract.id, history: history.id, uploadedFile: stored.file_url };
  console.log('PASS disposable API fixtures: 2 tenants, 2 contracts, 30 scoped/unrelated documents');

  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] });
  await ownerContext.addInitScript(id => {
    if (window.top !== window.self) return;
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true }));
  }, ownerProfile.id);
  owner = await ownerContext.newPage();
  observe(owner);
  if (!await step('owner real UI login', async () => { await loginUI(owner, process.env.QA_OWNER || 'mat.thias'); return 'Owner authenticated by visible login form'; })) throw new Error('The owner login prerequisite failed; remaining checks were skipped.');
  results.bundleAssets = await owner.evaluate(() => [...document.querySelectorAll('script[src], link[rel="stylesheet"]')].map(element => element.getAttribute('src') || element.getAttribute('href')));
  await step('tenant name opens information card with contacts, individual rents and historical contract', async () => {
    await owner.goto(`${base}/tenants`);
    const offer = owner.getByRole('button', { name: 'Später', exact: true });
    if (await offer.isVisible().catch(() => false)) await offer.click();
    await owner.locator('.data-table-wrapper .search-input').fill(tenant.full_name);
    await owner.getByRole('button', { name: tenant.full_name, exact: true }).click();
    const card = owner.getByRole('dialog', { name: tenant.full_name });
    await expect(card.getByRole('link', { name: tenant.email })).toHaveAttribute('href', `mailto:${tenant.email}`);
    await expect(card.getByText(contract.contract_number, { exact: true })).toBeVisible();
    await expect(card.getByText(history.contract_number, { exact: true })).toBeVisible();
    await expect(card.getByText('800,00 €', { exact: true })).toBeVisible();
    await expect(card.getByText('550,00 €', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Kopieren: Adresse' }).click();
    assert.equal((await owner.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n'), 'QA Lindenstraße 8\n10115 Berlin\nDE');
    const dimensions = await screenshot(owner, 'party-overview-1440.png', 'party overview');
    const overviewTab = card.getByRole('tab', { name: 'Übersicht', exact: true });
    await overviewTab.focus();
    await owner.keyboard.press('ArrowRight');
    await expect(card.getByRole('tab', { name: /Dokumente/ })).toBeFocused();
    await owner.keyboard.press('ArrowLeft');
    await expect(overviewTab).toBeFocused();
    return dimensions;
  });
  await step('historical document preview, real PDF download, nested Escape and focus restoration', async () => {
    const card = owner.getByRole('dialog', { name: tenant.full_name });
    await card.getByRole('tab', { name: /Dokumente/ }).click();
    await expect(card.getByRole('button', { name: historicalDoc.title, exact: true })).toBeVisible();
    await expect(card.getByText(`${marker} Fremdes Einheitendokument`, { exact: true })).toHaveCount(0);
    const opener = card.getByRole('button', { name: historicalDoc.title, exact: true });
    await opener.click();
    const viewer = owner.getByRole('dialog', { name: historicalDoc.title, exact: true });
    await expect(viewer.locator('iframe')).toHaveAttribute('src', `${base}${stored.file_url}`);
    const downloadEvent = owner.waitForEvent('download', { timeout: 10000 });
    await viewer.getByRole('button', { name: 'Herunterladen', exact: true }).click();
    const download = await downloadEvent;
    const downloadPath = path.join(output, 'historical-download.pdf');
    await download.saveAs(downloadPath);
    assert.deepEqual(await fs.readFile(downloadPath), pdfBuffer, 'Downloaded PDF differs from uploaded bytes');
    await owner.keyboard.press('Escape');
    await expect(viewer).toHaveCount(0);
    await expect(card).toBeVisible();
    await expect(opener).toBeFocused();
    await screenshot(owner, 'party-documents-1440.png', 'party documents');
    await owner.keyboard.press('Escape');
    await expect(card).toHaveCount(0);
    await expect(owner.getByRole('button', { name: tenant.full_name, exact: true })).toBeFocused();
    return { download: 'historical-download.pdf', bytes: pdfBuffer.length, unrelatedUnitDocumentExcluded: true };
  });
  await step('direct tenant without a contract: 26 document pages, search, type filter and grid', async () => {
    await gotoDocuments(owner, direct.id);
    await owner.getByRole('button', { name: 'Parteienkarte öffnen' }).click();
    const card = owner.getByRole('dialog', { name: direct.full_name });
    await card.getByRole('tab', { name: /Dokumente/ }).click();
    await expect(card.getByRole('listitem')).toHaveCount(25);
    await card.getByRole('button', { name: 'Weitere Dokumente laden', exact: true }).click();
    await expect(card.getByRole('listitem')).toHaveCount(26);
    await expect(card.getByRole('button', { name: 'Weitere Dokumente laden', exact: true })).toHaveCount(0);
    await card.getByRole('searchbox').fill('Direkt 01');
    await expect(card.getByRole('listitem')).toHaveCount(1);
    await card.getByRole('searchbox').fill('');
    await card.getByLabel('Dokumententyp').selectOption('Brief');
    await expect(card.getByRole('listitem')).toHaveCount(13);
    await card.getByRole('button', { name: 'Kartenansicht', exact: true }).click();
    await expect(card.locator('.party-document-collection-grid')).toBeVisible();
    await screenshot(owner, 'direct-documents-grid-1440.png', 'party document grid');
    await owner.keyboard.press('Escape');
    await expect(owner.getByRole('navigation', { name: 'Dokumentseiten' })).toContainText('1–25 von 26');
    await owner.getByRole('button', { name: 'Weitere Dokumente', exact: true }).click();
    await expect(owner.getByRole('navigation', { name: 'Dokumentseiten' })).toContainText('26–26 von 26');
    return 'Panel and full Documents page both expose all 26 directly owned documents';
  });
  await step('CSV export contains all 26 scoped documents and honors server search and type filters', async () => {
    await gotoDocuments(owner, direct.id);
    const exportCsv = async (filename, expectedRows) => {
      const downloadEvent = owner.waitForEvent('download', { timeout: 10000 });
      await owner.getByRole('button', { name: 'CSV', exact: true }).click();
      const download = await downloadEvent;
      const target = path.join(output, filename);
      await download.saveAs(target);
      const csv = (await fs.readFile(target, 'utf8')).replace(/^\uFEFF/, '').trim();
      const rows = csv.split(/\r?\n/).slice(1);
      assert.equal(rows.length, expectedRows, `${filename} must contain ${expectedRows} data rows`);
      assert.ok(rows.every(row => row.includes(marker) && row.includes('Direkt')), 'CSV leaked documents from another party');
      return { filename, rows: rows.length };
    };
    const all = await exportCsv('direct-documents-all.csv', 26);
    await owner.getByLabel('Dokumente durchsuchen', { exact: true }).fill('Direkt 01');
    await expect(owner.getByRole('navigation', { name: 'Dokumentseiten' })).toContainText('1–1 von 1');
    const search = await exportCsv('direct-documents-search.csv', 1);
    await owner.getByLabel('Dokumente durchsuchen', { exact: true }).fill('');
    await owner.getByLabel('Dokumententyp', { exact: true }).selectOption('Brief');
    await expect(owner.getByRole('navigation', { name: 'Dokumentseiten' })).toContainText('1–13 von 13');
    const type = await exportCsv('direct-documents-type.csv', 13);
    return { all, search, type };
  });
  await step('single real file upload opens metadata form and persists direct tenant ownership', async () => {
    await gotoDocuments(owner, tenant.id);
    await owner.getByLabel('Dokumentdateien wählen').setInputFiles(path.join(output, 'qa-single.pdf'));
    const dialog = owner.getByRole('dialog', { name: 'Dokument erstellen' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Mieter / Partei', { exact: true })).toHaveValue(tenant.id);
    await dialog.getByLabel(/^Titel/).fill(`${marker} Browser Einzelupload`);
    const saveResponse = owner.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/documents' && response.request().method() === 'POST', { timeout: 10000 });
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    const saved = await saveResponse;
    assert.equal(saved.status(), 201, `Single upload save returned ${saved.status()}`);
    const data = await saved.json();
    assert.equal(data.tenant_id, tenant.id);
    assert.equal(data.contract_id, null);
    assert.ok(data.file_url.startsWith('/uploads/'));
    const fetched = await call('GET', `/documents/${data.id}`);
    assert.equal(fetched.title, `${marker} Browser Einzelupload`);
    assert.equal(fetched.tenant_id, tenant.id);
    await expect(dialog).toHaveCount(0);
    return { document: data.id, directlyAssigned: true };
  });
  await step('multiple real file uploads import both documents with server-confirmed party ownership', async () => {
    const imported = [];
    const capture = async response => {
      if (new URL(response.url()).pathname === '/api/v1/documents/import' && response.request().method() === 'POST') imported.push({ status: response.status(), data: await response.json() });
    };
    owner.on('response', capture);
    try {
      await owner.getByLabel('Dokumentdateien wählen').setInputFiles([path.join(output, 'qa-batch-a.pdf'), path.join(output, 'qa-batch-b.pdf')]);
      await expect(owner.getByRole('status').filter({ hasText: 'qa-batch-a.pdf' })).toContainText('Gespeichert', { timeout: 15000 });
      await expect(owner.getByRole('status').filter({ hasText: 'qa-batch-b.pdf' })).toContainText('Gespeichert', { timeout: 15000 });
      await expect.poll(() => imported.length, { timeout: 10000 }).toBe(2);
      assert.ok(imported.every(value => value.status === 201 && value.data.tenant_id === tenant.id));
      const page = await call('GET', `/tenants/${tenant.id}/documents?limit=100`);
      assert.equal(page.items.filter(value => ['qa-batch-a', 'qa-batch-b'].includes(value.title)).length, 2);
      return imported.map(value => ({ id: value.data.id, title: value.data.title, directTenant: value.data.tenant_id }));
    } finally { owner.off('response', capture); }
  });
  for (const width of [1440, 360, 320]) {
    await step(`real Documents page at ${width}px without horizontal overflow`, async () => {
      await owner.setViewportSize({ width, height: 1000 });
      await gotoDocuments(owner, tenant.id);
      await expect(owner.locator('.data-table-wrapper')).toBeVisible();
      return await screenshot(owner, `documents-page-${width}.png`, 'documents page');
    });
    await step(`real party overview, documents and grid at ${width}px without panel overflow`, async () => {
      await owner.getByRole('button', { name: 'Parteienkarte öffnen' }).click();
      const card = owner.getByRole('dialog', { name: tenant.full_name });
      await expect(card.getByRole('link', { name: tenant.email })).toBeVisible();
      await screenshot(owner, `party-overview-${width}.png`, 'party overview');
      await card.getByRole('tab', { name: /Dokumente/ }).click();
      await expect(card.getByRole('list')).toBeVisible();
      await screenshot(owner, `party-documents-${width}.png`, 'party documents');
      await card.getByRole('button', { name: 'Kartenansicht', exact: true }).click();
      await screenshot(owner, `party-grid-${width}.png`, 'party document grid');
      const pdfResponse = owner.waitForResponse(response => response.url() === `${base}${stored.file_url}`, { timeout: 10000 });
      await card.getByRole('button', { name: historicalDoc.title, exact: true }).click();
      const preview = owner.getByRole('dialog', { name: historicalDoc.title, exact: true });
      await expect(preview.locator('iframe')).toBeVisible();
      await (await pdfResponse).finished();
      await screenshot(owner, `party-preview-${width}.png`, 'party PDF preview');
      const previewSize = await preview.evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
      assert.ok(previewSize.scrollWidth <= previewSize.width + 1, `Preview overflows: ${JSON.stringify(previewSize)}`);
      await owner.keyboard.press('Escape');
      await expect(preview).toHaveCount(0);
      await owner.keyboard.press('Escape');
      return { width, screenshots: 4 };
    });
  }
  await step('read-only real UI login and no edit/upload controls on party or Documents page', async () => {
    const login = await api.post('/api/v1/auth/login', { data: { username: process.env.QA_READONLY || 'stb.hofmann', password } });
    assert.equal(login.status(), 200, 'Read-only API login failed');
    const token = (await login.json()).access_token;
    const profileResponse = await api.get('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } });
    const profile = await profileResponse.json();
    assert.equal(profile.role, 'readonly');
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    await context.addInitScript(id => {
      if (window.top !== window.self) return;
      localStorage.setItem('locale', 'de-DE');
      localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true }));
    }, profile.id);
    readonly = await context.newPage();
    observe(readonly);
    await loginUI(readonly, process.env.QA_READONLY || 'stb.hofmann');
    await gotoDocuments(readonly, tenant.id);
    await expect(readonly.locator('.data-table-wrapper')).toBeVisible();
    await expect(readonly.getByRole('button', { name: 'Dokumente hochladen' })).toHaveCount(0);
    await expect(readonly.getByLabel('Dokumentdateien wählen')).toHaveCount(0);
    await expect(readonly.getByRole('button', { name: 'Bearbeiten', exact: true })).toHaveCount(0);
    await expect(readonly.getByRole('button', { name: 'Löschen', exact: true })).toHaveCount(0);
    await readonly.getByRole('button', { name: 'Parteienkarte öffnen' }).click();
    const card = readonly.getByRole('dialog', { name: tenant.full_name });
    await expect(card.getByRole('link', { name: 'Mieter bearbeiten' })).toHaveCount(0);
    await card.getByRole('tab', { name: /Dokumente/ }).click();
    await expect(card.getByRole('list')).toBeVisible();
    await expect(card.getByRole('link', { name: 'Dokument hinzufügen' })).toHaveCount(0);
    await screenshot(readonly, 'readonly-party-documents-1440.png', 'read-only party documents');
    return 'Read-only can view party documents; mutation controls are absent';
  });
} catch (error) {
  results.checks.push({ name: 'fixture setup or runner', status: 'fail', error: error.message });
  console.log(`FAIL runner: ${error.message}`);
} finally {
  await bounded(browser.close(), 10000, 'browser cleanup').catch(error => { results.browserCleanupError = error.message; });
  if (api) {
    // Only IDs created by this run are deleted. Existing seed data is untouched.
    const unique = [...new Map(entities.map(value => [`${value.collection}/${value.id}`, value])).values()];
    const priority = { documents: 0, contracts: 1, tenants: 2, units: 3, properties: 4, portfolios: 5 };
    for (const entity of unique.sort((a, b) => priority[a.collection] - priority[b.collection])) {
      const response = await api.delete(`/api/v1/${entity.collection}/${entity.id}`, { timeout: 10000 }).catch(error => ({ status: () => -1, text: async () => error.message }));
      results.cleanup.push({ ...entity, status: response.status(), ...(response.status() !== 204 ? { error: await response.text() } : {}) });
    }
    await api.dispose();
  }
  results.finished = new Date().toISOString();
  results.summary = { passed: results.checks.filter(value => value.status === 'pass').length, failed: results.checks.filter(value => value.status === 'fail').length, consoleErrors: results.consoleErrors.length, apiFailures: results.apiFailures.length, cleanupFailures: results.cleanup.filter(value => value.status !== 204).length };
  await fs.mkdir(output, { recursive: true });
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results.summary));
  process.exitCode = results.summary.failed || results.summary.consoleErrors || results.summary.cleanupFailures ? 1 : 0;
}
