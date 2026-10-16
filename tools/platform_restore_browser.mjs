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
const { chromium, request } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
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
  const introduction = page.getByRole('button', { name: 'Später', exact: true });
  if (await introduction.isVisible().catch(() => false)) await introduction.click();
  await page.getByRole('heading', { name: /Verwaltungsübersicht/i }).waitFor({ timeout: 20000 });
  // The app authorizes /uploads with its per-session bearer token, not a
  // public URL or the browser context's cookie jar. Keep the token entirely
  // inside this synthetic QA process; never print it in logs or artifacts.
  const bearer = await page.evaluate(() => localStorage.getItem('access_token'));
  if (!bearer) throw Error('Restored browser has no authenticated access token');
  const originals = Object.entries(spec.originals);
  const anonymous = await request.newContext({ baseURL: spec.base });
  try {
    for (const [key, expected] of originals) {
      const uri = `${spec.base}/uploads/${key}`;
      const denied = await anonymous.get(uri);
      if (denied.status() !== 401) throw Error('A separate anonymous browser client can access a restored original');
      const response = await page.request.get(uri, { headers: { Authorization: `Bearer ${bearer}` } });
      if (!response.ok() || createHash('sha256').update(await response.body()).digest('hex') !== expected)
        throw Error('Browser original hash mismatch');
    }
  } finally {
    await anonymous.dispose();
  }
  for (const width of [320, 360, 1440]) {
    await page.setViewportSize({ width, height: 850 });
    // Mobile navigation deliberately hides the desktop logout button. The
    // correct invariant is an authenticated workspace at every breakpoint.
    const stillAuthenticated = await page.evaluate(
      () => Boolean(localStorage.getItem('access_token')));
    if (!stillAuthenticated || new URL(page.url()).pathname === '/login')
      throw Error('Restored session disappeared after changing viewport');
    await page.getByRole('heading', { name: /Verwaltungsübersicht/i }).waitFor({ timeout: 20000 });
    const layout = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth,
                                               expected: window.innerWidth }));
    if (layout.actual > layout.expected + 2) throw Error('Restored dashboard horizontal overflow at ' + width);
    if (spec.screenshots) await page.screenshot({ path: spec.screenshots + '-dashboard-' + width + '.png', fullPage: true });
  }
  // Also exercise the real plugin/storage settings UI, not just a login shell.
  await page.goto(spec.base + '/settings?section=system');
  const showPlatform = page.getByRole('button', { name: /Speicher und Plugins anzeigen/i });
  await showPlatform.waitFor({ timeout: 20000 });
  await showPlatform.click();
  await page.getByRole('heading', { name: 'Speicher und Plugins' }).waitFor({ timeout: 20000 });
  await page.getByText('Lokaler Speicher', { exact: true }).waitFor({ timeout: 20000 });
  for (const width of [320, 360, 1440]) {
    await page.setViewportSize({ width, height: 850 });
    await page.getByRole('heading', { name: 'Speicher und Plugins' }).waitFor({ timeout: 12000 });
    const layout = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth,
                                               expected: window.innerWidth }));
    if (layout.actual > layout.expected + 2) throw Error('Platform settings horizontal overflow at ' + width);
    const restoreButton = page.getByRole('button', { name: /Wiederherstellungsprobe starten/i });
    const visibleButton = await restoreButton.evaluate(element => {
      const outer = element.getBoundingClientRect();
      const parent = element.closest('[data-testid="operations-section"]').getBoundingClientRect();
      return outer.left >= 0 && outer.right <= window.innerWidth + 1
        && outer.left >= parent.left - 1 && outer.right <= parent.right + 1;
    });
    if (!visibleButton) throw Error('Restore action button is clipped at ' + width);
    if (spec.screenshots) await page.screenshot({ path: spec.screenshots + '-platform-' + width + '.png', fullPage: true });
  }
  if (errors.length) throw Error('Browser console errors');
  console.log(JSON.stringify({ ok: true, readiness: 'browser_verified', originals: originals.length,
    widths: [320, 360, 1440], screens: ['dashboard', 'platform'],
    authenticated: true, private_denial: true }));
} finally { await browser.close(); }
