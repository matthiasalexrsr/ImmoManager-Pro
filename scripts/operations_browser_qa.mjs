import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1'
  || !process.env.QA_PASSWORD || !process.env.QA_PLAYWRIGHT_PATH) throw Error('Owned synthetic application required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], pages: [], page_errors: [], server_errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let api, context, page;
let current = 'setup';
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  current = name;
  try { await action(); report.checks.push({ name, ok: true }); console.log('PASS ' + name); }
  catch (error) {
    report.checks.push({ name, ok: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    if (page) await fs.writeFile(path.join(output, 'failure-dom.html'), await page.content());
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function fits() {
  const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(size.document <= size.viewport + 1, `${current}: page overflow ${JSON.stringify(size)}`);
}
async function shot(name) { await fits(); await page.screenshot({ path: path.join(output, name) }); }
const row = text => page.locator('.data-table tbody tr').filter({ hasText: text });
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const login = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok());
  const token = (await login.json()).access_token;
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + token } });
  await setup.dispose();
  const owner = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Betriebsabläufe' });
  const north = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Nordhaus', property_type: 'residential' });
  const south = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Südhaus', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: north.id, label: 'QA Nordwohnung', unit_type: 'flat' });
  const otherUnit = await call('POST', '/units', { property_id: south.id, label: 'QA Südwohnung', unit_type: 'flat' });
  const record = await call('POST', '/maintenance', { title: 'QA Dachschaden', property_id: north.id, unit_id: unit.id,
    appointment_at: '2026-11-03T14:35:27.123', priority: 'high' });
  const series = await call('POST', '/tasks', { title: 'QA Aufgabenserie', property_id: north.id, unit_id: unit.id,
    recurrence_rule: 'FREQ=MONTHLY', due_date: '2026-01-01' });
  const appointment = await call('POST', `/maintenance/${record.id}/appointments`, {
    title: 'QA Dachbegehung', event_date: '2026-11-04', event_time: '14:35', kind: 'inspection', description: 'Dach und Rinne gemeinsam prüfen.' });
  const unrelated = await call('POST', '/calendar', { title: 'QA Fremder Termin', event_type: 'meeting', event_date: '2026-11-04', property_id: south.id });
  assert.ok(unrelated.id);
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  await context.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, owner.id);
  await context.route('**/*', route => {
    const target = new URL(route.request().url());
    if (!['http:', 'https:'].includes(target.protocol) || target.origin === base.origin) return route.continue();
    report.external.push(target.origin + target.pathname); return route.abort('blockedbyclient');
  });
  page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => report.page_errors.push({ page: current, error: String(error) }));
  page.on('console', message => { if (message.type() === 'error' && /(?:Content.Security.Policy|ErrorBoundary caught:)/i.test(message.text())) report.page_errors.push({ page: current, error: `UI console: ${message.text()}` }); });
  page.on('response', response => {
    if (response.status() >= 500 && new URL(response.url()).origin === base.origin) report.server_errors.push({ page: current, path: new URL(response.url()).pathname, status: response.status() });
  });
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');

  let newTask;
  await step('Create a task from a unit file, retain its context and open readable task details', async () => {
    await page.goto(`${base.origin}/tasks?unit_id=${unit.id}`);
    await expect(page.getByRole('navigation', { name: 'Objektbezug' })).toContainText(unit.label);
    await page.getByRole('button', { name: 'Neu', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Aufgabe erstellen' });
    await expect(dialog.getByLabel('Immobilie')).toHaveValue(north.id);
    await expect(dialog.getByLabel('Einheit')).toHaveValue(unit.id);
    await dialog.getByLabel('Titel', { exact: false }).fill('QA Rückruf zur Dachbegehung');
    await dialog.getByLabel('Beschreibung').fill('Vor der Begehung mit der Partei abstimmen.');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    newTask = (await call('GET', '/tasks?limit=1000')).find(task => task.title === 'QA Rückruf zur Dachbegehung');
    assert.equal(newTask.property_id, north.id); assert.equal(newTask.unit_id, unit.id);
    await row(newTask.title).getByRole('link', { name: newTask.title }).click();
    await expect(page.getByRole('region', { name: 'Aufgabendetails' })).toContainText('Vor der Begehung mit der Partei abstimmen.');
    await shot('task-details-1440.png');
  });
  await step('End a recurring series in the UI and verify that manual generation creates no children', async () => {
    await page.goto(`${base.origin}/tasks?focus_id=${series.id}`);
    await row(series.title).getByRole('button', { name: 'Serie beenden', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/tasks/${series.id}`)).status).toBe('cancelled');
    const generated = await call('POST', '/tasks/generate-recurring/report?as_of=2026-03-01', {});
    assert.ok(!generated.created.some(task => task.parent_task_id === series.id));
    await expect(page.getByRole('region', { name: 'Aufgabendetails' })).toContainText('Serie beendet');
  });
  await step('Edit a damage case without losing its timestamp, then deliberately reschedule its local time', async () => {
    await page.goto(`${base.origin}/maintenance?unit_id=${unit.id}`);
    await row(record.title).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    let dialog = page.getByRole('dialog', { name: 'Wartungsauftrag bearbeiten' });
    await expect(dialog.getByLabel('Termin')).toHaveValue('2026-11-03T14:35:27');
    await dialog.getByLabel('Zuständig').fill('QA Verwaltung');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await expect(dialog).toHaveCount(0);
    assert.equal((await call('GET', `/maintenance/${record.id}`)).appointment_at, record.appointment_at);
    await row(record.title).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Wartungsauftrag bearbeiten' });
    await dialog.getByLabel('Termin').fill('2026-11-05T16:45');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await expect(dialog).toHaveCount(0);
    assert.equal((await call('GET', `/maintenance/${record.id}`)).appointment_at, '2026-11-05T16:45:00');
    await row(record.title).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Wartungsauftrag bearbeiten' });
    await expect(dialog.getByLabel('Termin')).toHaveValue('2026-11-05T16:45');
    await dialog.getByLabel('Immobilie', { exact: false }).selectOption(south.id);
    await expect(dialog.getByLabel('Einheit')).toHaveValue('');
    await expect(dialog.getByLabel('Einheit')).not.toContainText(unit.label);
    await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
    const discard = page.getByRole('button', { name: 'Verwerfen', exact: true });
    if (await discard.isVisible().catch(() => false)) await discard.click();
  });
  await step('Follow exact project → calendar → project links and retain only this project’s appointments', async () => {
    await page.goto(`${base.origin}/maintenance/${record.id}?tab=appointments`);
    await page.getByRole('link', { name: /QA Dachbegehung/ }).click();
    await expect(page.getByRole('region', { name: 'Termindetails' })).toContainText('Dach und Rinne gemeinsam prüfen.');
    await expect(row('QA Dachbegehung')).toHaveCount(1); await expect(row('QA Fremder Termin')).toHaveCount(0);
    assert.equal(new URL(page.url()).searchParams.get('focus_id'), appointment.calendar_event_id);
    await page.getByRole('link', { name: 'Projektakte und Termin bearbeiten' }).click();
    await expect(page.getByRole('tab', { name: 'Termine', exact: true })).toHaveAttribute('aria-selected', 'true');
    await shot('project-appointments-1440.png');
  });
  await step('Move a project to a corrected unit and verify all calendar references, refusing an inconsistent move', async () => {
    const rejected = await api.patch(`/api/v1/maintenance/${record.id}`, { data: { unit_id: otherUnit.id } });
    assert.equal(rejected.status(), 400);
    await call('PATCH', `/maintenance/${record.id}`, { property_id: south.id, unit_id: otherUnit.id });
    const event = await call('GET', `/calendar/${appointment.calendar_event_id}`);
    assert.equal(event.property_id, south.id); assert.equal(event.unit_id, otherUnit.id);
    assert.equal(event.maintenance_case_id, record.id); assert.equal(event.event_time, '14:35');
    const invalid = await api.patch(`/api/v1/calendar/${event.id}`, { data: { property_id: north.id, unit_id: unit.id } });
    assert.equal(invalid.status(), 409);
    await page.goto(`${base.origin}/calendar?maintenance_case_id=${record.id}&focus_id=${event.id}`);
    await expect(page.getByRole('region', { name: 'Termindetails' })).toContainText(otherUnit.label);
  });
  await step('Exercise date filters and preserve unit context when creating an appointment', async () => {
    await page.goto(`${base.origin}/calendar?unit_id=${otherUnit.id}&date_from=2026-11-01&date_to=2026-11-30`);
    await page.getByRole('button', { name: 'Neu', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Termin erstellen' });
    await expect(dialog.getByLabel('Immobilie')).toHaveValue(south.id);
    await expect(dialog.getByLabel('Einheit (optional)')).toHaveValue(otherUnit.id);
    await expect(dialog.getByLabel('Datum', { exact: false })).toHaveValue('2026-11-01');
    await dialog.getByLabel('Titel', { exact: false }).fill('QA Ablesung Süd');
    await dialog.getByLabel('Typ', { exact: false }).selectOption('meeting');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click(); await expect(dialog).toHaveCount(0);
    await expect(row('QA Ablesung Süd')).toHaveCount(1);
    await page.getByLabel('Von', { exact: true }).fill('2026-11-03');
    await expect(row('QA Ablesung Süd')).toHaveCount(0);
    await expect(row('QA Dachbegehung')).toHaveCount(1);
  });
  for (const width of [320, 360, 1440]) {
    await step(`Operational files and every project tab at ${width}px`, async () => {
      await page.setViewportSize({ width, height: 1000 });
      const routes = [`/tasks?focus_id=${newTask.id}`, `/calendar?maintenance_case_id=${record.id}&focus_id=${appointment.calendar_event_id}`,
        `/maintenance?unit_id=${otherUnit.id}`, ...['overview', 'work', 'appointments', 'procurement', 'costs', 'protocols', 'documents'].map(tab => `/maintenance/${record.id}?tab=${tab}`)];
      for (const route of routes) {
        current = route + ` (${width}px)`;
        await page.goto(base.origin + route); await page.waitForLoadState('networkidle'); await fits();
        assert.ok(!/\b(?:undefined|NaN|Invalid Date)\b/.test(await page.locator('body').innerText()));
        report.pages.push({ route, width, ok: true });
        if (route.startsWith('/tasks?')) await shot(`task-details-${width}.png`);
        if (route.startsWith('/calendar?')) await shot(`calendar-details-${width}.png`);
      }
      await shot(`operations-last-page-${width}.png`);
    });
  }
  assert.deepEqual(report.page_errors, []); assert.deepEqual(report.server_errors, []); assert.deepEqual(report.external, []);
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
