// UI pass for one user: every page loads without JS errors, failed requests or raw translation keys.
// Usage: node ui.js <origin> <username> <password> <out.json>
const fs = require('fs');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('@playwright/test')); }

const [origin, username, password, out] = process.argv.slice(2);
const PAGES = ['', 'portfolios', 'properties', 'units', 'tenants', 'contracts', 'accounts', 'bookings', 'invoices',
  'maintenance', 'tasks', 'documents', 'rent-overview', 'meters', 'contacts', 'statements', 'messages', 'categories',
  'deposits', 'insurances', 'calendar', 'leads', 'listings', 'viewings', 'rent-adjustments', 'budgets', 'tax-rates',
  'receivables', 'rent-charges', 'escalation-rules', 'notification-templates', 'history', 'allocation-keys',
  'handover-protocols', 'settings', 'review'];
const RAW_KEY = /\b(?:pages|ui|status|navigation|tenantsContracts|finance|portfolio|units|comp)\.[a-zA-Z]+\.[a-zA-Z.]+\b/g;

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'de-DE' });
  const issues = [];
  let current = 'login';
  page.on('pageerror', e => issues.push({ page: current, kind: 'js', detail: e.message.slice(0, 200) }));
  let requests = 0;
  let refused = new Map();   // url -> count of 403 answers on the current page
  page.on('request', r => { if (r.url().includes('/api/')) requests += 1; });
  page.on('response', r => {
    const url = r.url().replace(origin, '').split('?')[0];
    if (r.status() >= 500) issues.push({ page: current, kind: `http ${r.status()}`, detail: url });
    if (r.status() === 403 && url.includes('/api/')) refused.set(url, (refused.get(url) || 0) + 1);
  });
  await page.goto(`${origin}/login`);
  await page.waitForTimeout(800);
  await page.locator('input').nth(0).fill(username);
  await page.locator('input[type=password]').fill(password);
  await page.locator('button[type=submit]').click();
  await page.waitForTimeout(1500);
  const pages = [];
  for (const path of PAGES) {
    current = path || 'dashboard';
    const started = Date.now();
    requests = 0;
    refused = new Map();
    await page.goto(`${origin}/${path}`, { waitUntil: 'load' }).catch(e => issues.push({ page: current, kind: 'nav', detail: e.message }));
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => issues.push({ page: current, kind: 'kommt nicht zur Ruhe', detail: `${requests} API-Anfragen in 15 s` }));
    const ms = Date.now() - started;
    const text = await page.locator('body').innerText().catch(() => '');
    const raw = [...new Set(text.match(RAW_KEY) || [])];
    if (raw.length) issues.push({ page: current, kind: 'i18n', detail: raw.slice(0, 5).join(', ') });
    // only changing buttons: New, Edit, Delete (viewing a rent history is fine for read-only users)
    const editButtons = await page.locator('.action-cell button[aria-label="Bearbeiten"], .action-cell button[aria-label="Löschen"], .table-header .btn-primary').count();
    for (const [url, count] of refused) issues.push({ page: current, kind: 'http 403', detail: `${url} (${count}×)` });
    pages.push({ page: current, ms, editButtons, requests });
  }
  fs.writeFileSync(out, JSON.stringify({ username, pages, issues }, null, 1));
  await browser.close();
})();
