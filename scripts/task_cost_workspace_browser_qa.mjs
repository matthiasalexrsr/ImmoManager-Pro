/** Task recurrence and cost CRUD against an owned synthetic server and real APIs. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], screenshots: [], page_errors: [], external: [] };
let api, browser, context, page;
async function step(name, action) {
  try { await action(); report.checks.push({ name, passed: true }); }
  catch (error) { report.checks.push({ name, passed: false, error: String(error) }); await page?.screenshot({ path: path.join(output, `failure-${report.checks.length}.png`) }).catch(() => {}); throw error; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function post(endpoint, data) {
  const response = await api.post('/api/v1' + endpoint, { data });
  assert.ok(response.ok(), endpoint + ': ' + await response.text()); return response.json();
}
async function get(endpoint) {
  const response = await api.get('/api/v1' + endpoint); assert.ok(response.ok(), await response.text()); return response.json();
}
const responseFor = (method, pathname) => page.waitForResponse(response => response.request().method() === method && new URL(response.url()).pathname === '/api/v1' + pathname);
try {
  api = await request.newContext({ baseURL: base.origin });
  const login = await api.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok(), await login.text()); const token = (await login.json()).access_token;
  await api.dispose(); api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const profile = await get('/auth/me');
  const portfolio = await post('/portfolios', { name: 'Workspace QA Bestand' });
  const property = await post('/properties', { portfolio_id: portfolio.id, name: 'Workspace QA Haus', property_type: 'residential' });
  const unit = await post('/units', { property_id: property.id, label: 'Workspace QA Wohnung', unit_type: 'flat', area_sqm: 72 });
  const tenant = await post('/tenants', { full_name: 'Workspace QA Partei' });
  await post('/contracts', { contract_number: 'WORKSPACE-QA-2025', property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, start_date: '2024-01-01' });
  const period = await post('/billing/periods', { property_id: property.id, label: 'Workspace QA 2025', start_date: '2025-01-01', end_date: '2025-12-31' });
  const key = await post('/billing/allocation-keys', { property_id: property.id, name: 'Workspace QA Einheiten', key_type: 'unit_count' });
  await post('/billing/cost-items', { billing_period_id: period.id, description: 'Verbleibende Grundkosten', amount: 50, allocation_key_id: key.id });
  browser = await chromium.launch({ headless: true, ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await context.route('**/*', route => { const url = new URL(route.request().url()); if (!['http:', 'https:'].includes(url.protocol) || url.origin === base.origin) return route.continue(); report.external.push(url.origin + url.pathname); return route.abort('blockedbyclient'); });
  await context.addInitScript(({ token, id }) => { localStorage.setItem('access_token', token); localStorage.setItem('locale', 'de-DE'); localStorage.setItem(`immo.tutorial.${id}`, JSON.stringify({ offered: true })); }, { token, id: profile.id });
  page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(String(error)));
  let task, cost;
  await step('Create a custom recurring task with count through the actual form', async () => {
    await page.goto(base.origin + '/tasks'); await page.locator('[data-table-add]').click();
    const form = page.getByRole('dialog', { name: 'Aufgabe erstellen' });
    await expect(form.getByLabel('Titel *', { exact: true })).toBeEnabled();
    await form.getByLabel('Titel *', { exact: true }).fill('Workspace QA Serienprüfung');
    await form.getByLabel('Fällig am', { exact: true }).fill('2026-10-20');
    await form.getByLabel('Wiederholung', { exact: true }).selectOption('custom');
    await form.getByRole('combobox', { name: /^Häufigkeit/ }).selectOption('MONTHLY');
    await form.getByLabel('Intervall', { exact: true }).fill('3');
    await form.getByRole('combobox', { name: /^Ende der Wiederholung/ }).selectOption('count');
    await form.getByLabel('Anzahl der Folgeaufgaben', { exact: true }).fill('4');
    const screenshot = path.join(output, 'task-custom-recurrence.png'); await page.screenshot({ path: screenshot }); report.screenshots.push(screenshot);
    const response = responseFor('POST', '/tasks'); await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    const saved = await response; assert.ok(saved.ok(), await saved.text()); task = await saved.json();
    assert.equal(task.recurrence_rule, 'FREQ=MONTHLY;INTERVAL=3;COUNT=4'); await expect(form).toBeHidden();
  });
  await step('Reopen the retained rule and explicitly reset it to a one-off task', async () => {
    const row = page.getByRole('row').filter({ has: page.getByText('Workspace QA Serienprüfung', { exact: true }) });
    await row.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    const form = page.getByRole('dialog', { name: 'Aufgabe bearbeiten' });
    await expect(form.getByLabel('Wiederholung', { exact: true })).toBeEnabled();
    await expect(form.getByLabel('Intervall', { exact: true })).toHaveValue('3');
    await expect(form.getByLabel('Anzahl der Folgeaufgaben', { exact: true })).toHaveValue('4');
    await form.getByLabel('Wiederholung', { exact: true }).selectOption('none');
    const response = responseFor('PATCH', `/tasks/${task.id}`); await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    const saved = await response; assert.ok(saved.ok(), await saved.text()); assert.equal((await saved.json()).recurrence_rule, null);
    assert.equal((await get(`/tasks/${task.id}`)).recurrence_rule, null); await expect(form).toBeHidden();
  });
  await step('Create a cost in the focused period through the actual cost editor', async () => {
    await page.goto(`${base.origin}/statements?focus_id=${period.id}`);
    await expect(page.getByRole('heading', { name: period.label, exact: true })).toBeVisible();
    const costs = page.getByRole('region', { name: 'Kostenquellen dieser Abrechnung', exact: true });
    await expect(costs.getByText('Verbleibende Grundkosten', { exact: true })).toBeVisible();
    await costs.locator('[data-table-add]').click();
    const form = page.getByRole('dialog', { name: 'Kostenposition hinzufügen' });
    await expect(form.getByLabel('Kostenart *', { exact: true })).toBeEnabled();
    await form.getByLabel('Kostenart *', { exact: true }).fill('Workspace QA Wasser');
    await form.getByLabel('Betrag (€) *', { exact: true }).fill('100');
    await form.getByLabel('Verteilerschlüssel *', { exact: true }).selectOption(key.id);
    const response = responseFor('POST', '/billing/cost-items'); await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    const saved = await response; assert.ok(saved.ok(), await saved.text()); cost = await saved.json(); assert.equal(cost.billing_period_id, period.id);
    await expect(form).toBeHidden(); await expect(costs.getByText('Workspace QA Wasser', { exact: true })).toBeVisible();
  });
  await step('Edit and delete the same real cost with named confirmation and retained period binding', async () => {
    const costs = page.getByRole('region', { name: 'Kostenquellen dieser Abrechnung', exact: true });
    const row = costs.getByRole('row').filter({ has: page.getByText('Workspace QA Wasser', { exact: true }) });
    await row.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    const form = page.getByRole('dialog', { name: 'Kostenposition bearbeiten' });
    await expect(form.getByLabel('Betrag (€) *', { exact: true })).toBeEnabled();
    await form.getByLabel('Betrag (€) *', { exact: true }).fill('125.50');
    const update = responseFor('PUT', `/billing/cost-items/${cost.id}`); await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    const saved = await update; assert.ok(saved.ok(), await saved.text()); await expect(form).toBeHidden();
    const retained = await get(`/billing/cost-items/${cost.id}`); assert.equal(retained.amount, 125.5); assert.equal(retained.billing_period_id, period.id);
    await row.getByRole('button', { name: 'Löschen', exact: true }).click();
    const confirm = page.getByRole('dialog').filter({ hasText: 'Kostenposition „Workspace QA Wasser“' }); await expect(confirm).toBeVisible();
    const deletion = responseFor('DELETE', `/billing/cost-items/${cost.id}`); await confirm.getByRole('button', { name: 'Löschen', exact: true }).click();
    assert.equal((await deletion).status(), 204); await expect(row).toBeHidden();
    assert.equal((await api.get(`/api/v1/billing/cost-items/${cost.id}`)).status(), 404);
  });
  await step('Finalized real period is readable and offers neither cost nor metadata editing', async () => {
    await post(`/billing/periods/${period.id}/generate`, {}); await post(`/billing/periods/${period.id}/finalize`, {});
    await page.reload(); await expect(page.getByRole('heading', { name: period.label, exact: true })).toBeVisible();
    const costs = page.getByRole('region', { name: 'Kostenquellen dieser Abrechnung', exact: true });
    await expect(costs.getByText('Verbleibende Grundkosten', { exact: true })).toBeVisible();
    await expect(costs.getByRole('button', { name: 'Bearbeiten', exact: true })).toHaveCount(0);
    await expect(costs.getByRole('button', { name: 'Löschen', exact: true })).toHaveCount(0);
    await expect(costs.locator('[data-table-add]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Zeitraum bearbeiten', exact: true })).toHaveCount(0);
    const screenshot = path.join(output, 'finalized-period-readonly.png'); await page.screenshot({ path: screenshot, fullPage: true }); report.screenshots.push(screenshot);
  });
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external, []);
} finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); await context?.close(); await browser?.close(); await api?.dispose(); }
