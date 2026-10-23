// Coordinator-only real browser gate. Input on stdin contains synthetic credentials.
// PLAYWRIGHT_MODULE must name an explicitly supplied local module; no downloads.
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const spec = JSON.parse(input);
const url = new URL(spec.base);
if (url.hostname !== '127.0.0.1' || ['8000', '8765', ''].includes(url.port)) throw Error('Owned loopback server required');
if (!process.env.PLAYWRIGHT_MODULE) throw Error('Explicit local Playwright module required');
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.goto(spec.base);
  await page.getByLabel(/Benutzername/i).fill(spec.username);
  await page.getByLabel(/Passwort/i).fill(spec.password);
  await page.getByRole('button', { name: /Anmelden/i }).click();
  await page.getByRole('button', { name: /Abmelden/i }).waitFor({ timeout: 20000 });
  for (const [key, expected] of Object.entries(spec.originals)) {
    const response = await page.request.get(`${spec.base}/uploads/${key}`);
    if (!response.ok() || createHash('sha256').update(await response.body()).digest('hex') !== expected) throw Error('Browser original hash mismatch');
  }
  if (errors.length) throw Error('Browser console errors');
  if (spec.screenshot) await page.screenshot({ path: spec.screenshot, fullPage: true });
  console.log(JSON.stringify({ ok: true, readiness: 'browser_verified', originals: Object.keys(spec.originals).length }));
} finally { await browser.close(); }
