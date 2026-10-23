/** Real PDF.js controls and geometry on a newly owned local installation. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port)
  || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], screenshots: [], geometry: [], page_errors: [], external: [] };
let browser, context, api, page;
async function step(name, action) {
  try { await action(); report.checks.push({ name, passed: true }); }
  catch (error) {
    report.checks.push({ name, passed: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, `failure-${report.checks.length}.png`) }).catch(() => {});
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
try {
  api = await request.newContext({ baseURL: base.origin });
  const login = await api.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok(), await login.text());
  const token = (await login.json()).access_token;
  await api.dispose();
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const profile = await (await api.get('/api/v1/auth/me')).json();
  const bytes = await fs.readFile(process.env.QA_PDF_FIXTURE);
  const uploaded = await api.post('/api/v1/files/upload?folder=documents', { multipart: {
    file: { name: 'toolbar-fixture.pdf', mimeType: 'application/pdf', buffer: bytes },
  } });
  assert.ok(uploaded.ok(), await uploaded.text());
  const file = await uploaded.json();
  const title = 'PDF Toolbar QA';
  const created = await api.post('/api/v1/documents', { data: { title, file_url: file.file_url } });
  assert.ok(created.ok(), await created.text());
  const document = await created.json();
  browser = await chromium.launch({ headless: true,
    ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.route('**/*', route => {
    const target = new URL(route.request().url());
    if (!['http:', 'https:'].includes(target.protocol) || target.origin === base.origin) return route.continue();
    report.external.push(target.origin + target.pathname); return route.abort('blockedbyclient');
  });
  await context.addInitScript(({ token, owner }) => {
    localStorage.setItem('access_token', token); localStorage.setItem('locale', 'de-DE');
    localStorage.setItem(`immo.tutorial.${owner}`, JSON.stringify({ offered: true }));
  }, { token, owner: profile.id });
  page = await context.newPage();
  page.on('pageerror', error => report.page_errors.push(String(error)));
  await page.goto(`${base.origin}/documents?focus_id=${encodeURIComponent(document.id)}`);
  // the title leads to the document page; the row's eye button opens the quick view checked here
  await page.getByRole('row').filter({ hasText: title }).getByRole('button', { name: 'Dokument ansehen', exact: true }).click();
  const viewer = page.getByRole('dialog', { name: title, exact: true });
  await expect(viewer.getByRole('img', { name: /Seite 1 von 3/ })).toBeVisible();
  const toolbar = viewer.locator('.pdf-preview-toolbar');
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 900 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    // Global button transitions animate media-query height changes. Measure
    // the settled control size instead of capturing an intermediate frame.
    await expect.poll(() => toolbar.locator('button,input,select').evaluateAll(nodes =>
      Math.min(...nodes.map(node => node.getBoundingClientRect().height))))
      .toBeGreaterThanOrEqual(width <= 640 ? 44 : 32);
    await step(`Aligned, unclipped PDF toolbar at ${width}px`, async () => {
      const geometry = await toolbar.evaluate(node => {
        const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, centerY: r.y + r.height / 2 }; };
        const input = node.querySelector('input'); const zoom = node.querySelector('select');
        return { toolbar: rect(node), viewportWidth: innerWidth, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
          controls: [...node.querySelectorAll('button,input,select')].map(element => ({ label: element.getAttribute('aria-label') || element.textContent || 'page', ...rect(element) })),
          pageLabel: rect(node.querySelector(`label[for="${CSS.escape(input.id)}"]`)), pageInput: rect(input),
          zoomLabel: rect(node.querySelector(`label[for="${CSS.escape(zoom.id)}"]`)), zoom: rect(zoom) };
      });
      report.geometry.push({ width, ...geometry });
      assert.ok(geometry.scrollWidth <= geometry.clientWidth + 1, 'Toolbar must not scroll horizontally');
      for (const control of geometry.controls) {
        assert.ok(control.x >= geometry.toolbar.x - 1 && control.right <= geometry.toolbar.right + 1, `${control.label} clipped`);
        assert.ok(control.height >= (width <= 640 ? 44 : 32), `${control.label} control height`);
      }
      assert.ok(Math.abs(geometry.pageLabel.centerY - geometry.pageInput.centerY) <= 1, 'Page label/input alignment');
      assert.ok(Math.abs(geometry.zoomLabel.centerY - geometry.zoom.centerY) <= 1, 'Zoom label/select alignment');
      if (width === 1440) {
        const centers = geometry.controls.map(control => control.centerY);
        assert.ok(Math.max(...centers) - Math.min(...centers) <= 1, 'All desktop controls share one vertical center');
      }
      const screenshot = path.join(output, `pdf-toolbar-${width}.png`);
      await page.screenshot({ path: screenshot }); report.screenshots.push(screenshot);
    });
    await step(`Page, zoom, extracted text and keyboard controls at ${width}px`, async () => {
      const input = viewer.getByRole('spinbutton', { name: 'Seite', exact: true });
      await input.fill('2'); await input.press('Enter');
      await expect(viewer.getByRole('img', { name: /Seite 2 von 3/ })).toBeVisible();
      await viewer.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
      await expect(viewer.getByRole('img', { name: /Seite 3 von 3/ })).toBeVisible();
      await expect(viewer.getByRole('button', { name: 'Nächste Seite', exact: true })).toBeDisabled();
      await viewer.getByRole('button', { name: 'Vorherige Seite', exact: true }).click();
      const zoom = viewer.getByRole('combobox', { name: 'Zoom', exact: true });
      await zoom.selectOption('150');
      await expect.poll(() => viewer.locator('.pdf-preview-canvas').evaluate(node => parseFloat(node.style.width))).toBeGreaterThan(850);
      await zoom.selectOption('fit');
      await expect.poll(() => viewer.locator('.pdf-preview-viewport').evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
      const toggle = viewer.getByRole('button', { name: 'PDF-Text', exact: true });
      await toggle.click();
      await expect(viewer.locator('.pdf-preview-text')).toContainText('PDF Toolbar Fixture Seite 2');
      await expect(toggle).toHaveAttribute('aria-pressed', 'true');
      await toggle.click();
      await input.focus(); await page.keyboard.press('Tab');
      await expect(viewer.getByRole('button', { name: 'Seite anzeigen', exact: true })).toBeFocused();
      await page.keyboard.press('Tab'); await expect(viewer.getByRole('button', { name: 'Nächste Seite', exact: true })).toBeFocused();
      await page.keyboard.press('Tab'); await expect(zoom).toBeFocused();
      await page.keyboard.press('Tab'); await expect(toggle).toBeFocused();
    });
  }
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await browser?.close(); await api?.dispose();
}
