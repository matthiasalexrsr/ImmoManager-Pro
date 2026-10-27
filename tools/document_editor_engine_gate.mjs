// Standalone native editor gate; serves only built local assets and synthetic data.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [modulePath, fixturePath, outputPath] = process.argv.slice(2);
assert.ok(modulePath && fixturePath && outputPath, 'playwright module, DOCX fixture and output directory required');
const { chromium } = await import(pathToFileURL(path.resolve(modulePath)).href);
const root = path.resolve('frontend/public/document-editor');
const output = path.resolve(outputPath);
await fs.mkdir(output, { recursive: true });
const report = { externalRequests: [], errors: [], console: [], requests: [], completed: false };
const html = `<!doctype html><html lang="de"><link rel="stylesheet" href="/document-editor/editor.css">
<body><div id="editor"></div><script type="module">
import { mountEditor } from '/document-editor/editor.js';
const bytes = await (await fetch('/fixture.docx')).blob();
window.editor = mountEditor(document.querySelector('#editor'), new File([bytes], 'Pruefung.docx'), {
  onReady: () => { window.ready = true; }, onError: e => { window.openError = String(e); }
});</script></body></html>`;
const server = http.createServer(async (req, res) => {
  try {
    if (req.url === '/') { res.setHeader('content-type', 'text/html'); res.end(html); return; }
    if (req.url === '/fixture.docx') { res.end(await fs.readFile(path.resolve(fixturePath))); return; }
    const requested = path.resolve(root, '.' + decodeURIComponent(req.url.replace(/^\/document-editor/, '')));
    assert.ok(requested.startsWith(root + path.sep));
    res.setHeader('content-type', requested.endsWith('.css') ? 'text/css' : 'application/javascript');
    res.end(await fs.readFile(requested));
  } catch { res.statusCode = 404; res.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['http:', 'https:'].includes(url.protocol) || url.origin === origin) return route.continue();
    report.externalRequests.push(url.origin + url.pathname); return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(String(error)));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) report.console.push(message.text().slice(0, 1000)); });
  page.on('response', response => report.requests.push({ url: response.url().replace(origin, ''), status: response.status() }));
  await page.goto(origin);
  try { await page.waitForFunction(() => window.ready || window.openError, null, { timeout: 60000 }); }
  catch (error) {
    report.body = (await page.locator('body').innerText()).slice(0, 10000);
    await page.screenshot({ path: path.join(output, 'editor-failed.png'), fullPage: true });
    throw error;
  }
  assert.equal(await page.evaluate(() => window.openError), undefined);
  report.buttons = await page.locator('button,[role="button"]').allTextContents();
  report.toolbarGeometry = await page.locator('[aria-label="Dokument formatieren und prüfen"] button').evaluateAll(nodes => nodes.map(node => ({
    label: node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent,
    rect: node.getBoundingClientRect().toJSON(), display: getComputedStyle(node).display,
    visibility: getComputedStyle(node).visibility,
  })));
  report.inputs = await page.locator('textarea,input,[contenteditable]').evaluateAll(nodes => nodes.map(node => ({
    tag: node.tagName, role: node.getAttribute('role'), label: node.getAttribute('aria-label'),
    editable: node.getAttribute('contenteditable'), className: node.className,
  })));
  await page.screenshot({ path: path.join(output, 'editor-open.png'), fullPage: true });
  assert.ok(report.buttons.length > 10, 'Real v2 formatting toolbar must be present');
  // V2 paints the document on canvas and accepts native keyboard composition
  // through its accessible textarea; it has no editable HTML document body.
  await page.locator('.superdoc-fragment').filter({ hasText: 'Prüfdokument:' }).first().click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('Control+Home');
  await page.keyboard.type('QA_BROWSER_AENDERUNG_20261016 ', { delay: 20 });
  await page.waitForFunction(() => document.body.innerText.includes('QA_BROWSER_AENDERUNG_20261016'));
  const base64 = await page.evaluate(async () => {
    const blob = await window.editor.exportDocx();
    return new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.readAsDataURL(blob); });
  });
  await fs.writeFile(path.join(output, 'native-editor-roundtrip.docx'), Buffer.from(base64, 'base64'));
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.screenshot({ path: path.join(output, `editor-${width}.png`), fullPage: true });
  }
  assert.deepEqual(report.externalRequests, []);
  assert.deepEqual(report.errors, []);
  report.completed = true;
} finally {
  await fs.writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
