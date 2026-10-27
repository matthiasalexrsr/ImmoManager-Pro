import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const { chromium, expect } = await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
if (process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const base = new URL(process.env.QA_BASE_URL);
if (!['127.0.0.1', 'localhost'].includes(base.hostname)) throw Error('Loopback required');
const out = path.resolve(process.env.QA_OUTPUT); await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ locale: 'de-DE', viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await context.newPage(); page.setDefaultTimeout(30000);
const result = { checks: [], pageErrors: [] };
page.on('pageerror', error => result.pageErrors.push(String(error)));
async function download(name) {
  const event = page.waitForEvent('download');
  await page.locator('#download-pdf').click();
  const file = await event;
  assert.equal(await file.failure(), null);
  const target = path.join(out, name); await file.saveAs(target);
  assert.equal((await fs.readFile(target)).subarray(0, 5).toString(), '%PDF-');
}
try {
  await page.goto(base.origin + '/mietvertrag/');
  await page.locator('[name="vermieter-name"]').fill('QA Vermieter Umlaut Müller');
  await page.locator('#step-1 .next').click();
  await page.locator('[name="mieter-name"]').fill('QA Mieter Beispiel');
  await page.locator('#step-2 .next').click();
  await page.locator('#objekt-strasse').fill('Prüfstraße 12');
  for (let step = 3; step < 8; step++) {
    if (step === 5) await page.locator('#miete-grund').fill('100,50');
    await page.locator('#step-' + step + ' .next').click();
  }
  await expect(page.locator('#vertragstext')).toContainText('QA Vermieter Umlaut Müller');
  await expect(page.locator('#vertragstext')).toContainText('100,50');
  await fs.writeFile(path.join(out, 'preview.txt'), await page.locator('#vertragstext .contract-container').innerText());
  result.checks.push('Wizard carries entered names and address to the contract');
  const response = page.waitForResponse(r => r.url().endsWith('/mietvertrag/api/pdf') && r.request().method() === 'POST');
  await download('wizard-server.pdf');
  assert.equal((await response).status(), 200);
  result.checks.push('Server PDF downloads through the actual button');
  await page.route('**/mietvertrag/api/pdf', route => route.fulfill({ status: 503, body: 'Synthetic unavailable PDF service' }));
  await download('wizard-browser-fallback.pdf');
  result.checks.push('Updated offline pdfmake fallback downloads when server PDF fails');
  // An imported/entered party name must remain visible text in preview and HTML export.
  for (let step = 8; step > 1; step--) await page.locator('#step-' + step + ' .prev').click();
  const hostile = '<img src="missing" onerror="window.wizardInjection=1"> & Müller';
  await page.locator('[name="vermieter-name"]').fill(hostile);
  for (let step = 1; step < 8; step++) await page.locator('#step-' + step + ' .next').click();
  await expect(page.locator('#vertragstext')).toContainText(hostile);
  assert.equal(await page.locator('#vertragstext img').count(), 0);
  assert.equal(await page.evaluate(() => window.wizardInjection), undefined);
  const htmlEvent = page.waitForEvent('download');
  await page.locator('#download').click();
  const html = await htmlEvent;
  await html.saveAs(path.join(out, 'wizard-escaped.html'));
  const saved = await fs.readFile(path.join(out, 'wizard-escaped.html'), 'utf8');
  assert.ok(saved.includes('&lt;img'));
  assert.ok(!saved.includes('<img src="missing"'));
  result.checks.push('Markup in party names remains literal in preview and downloaded HTML');
  await page.screenshot({ path: path.join(out, 'wizard-summary.png'), fullPage: true });
  assert.deepEqual(result.pageErrors, []);
  result.checks.push('No unhandled browser errors');
} finally {
  await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(result, null, 2));
  await context.close(); await browser.close();
}
console.log(JSON.stringify({ passed: result.checks.length, errors: result.pageErrors.length }));
