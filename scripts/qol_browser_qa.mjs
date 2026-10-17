/** Real everyday workflows, isolated synthetic installation; never ports 8000/8765. */
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
const report = { synthetic_only: true, checks: [], page_errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let context, api, page, reader;
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()}`);
  return response.status() === 204 ? null : response.json();
}
async function login(username, password, userId) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await ctx.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, userId);
  const tab = await ctx.newPage();
  tab.setDefaultTimeout(30000);
  tab.on('pageerror', error => report.page_errors.push(String(error)));
  tab.on('request', req => { if (/^https?:/.test(req.url()) && new URL(req.url()).origin !== base.origin) report.external.push(req.url()); });
  await tab.goto(base.origin + '/login');
  await tab.locator('input[autocomplete="username"]').fill(username);
  await tab.locator('input[type="password"]').fill(password);
  await tab.locator('form button[type="submit"]').click();
  await tab.waitForURL(url => url.pathname === '/');
  return [ctx, tab];
}
async function step(name, run) {
  try { await run(); report.checks.push({ name, ok: true }); }
  catch (error) {
    report.checks.push({ name, ok: false, error: String(error) });
    await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function fitsViewport(tab) {
  assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Document must not scroll horizontally');
}
try {
  const bootstrap = await request.newContext({ baseURL: base.origin });
  const response = await bootstrap.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok());
  const headers = { Authorization: 'Bearer ' + (await response.json()).access_token };
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: headers });
  await bootstrap.dispose();
  const user = await call('GET', '/auth/me');
  const suffix = Date.now().toString(36);
  const portfolio = await call('POST', '/portfolios', { name: 'QA Alltag ' + suffix });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Parkhof ' + suffix, property_type: 'residential', address_line: 'Am Park 12', city: 'Musterstadt' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'QA Wohnung ' + suffix, unit_type: 'flat', cold_rent: 750, status: 'vacant' });
  const parking = await call('POST', '/units', { property_id: property.id, label: 'QA Stellplatz ' + suffix, unit_type: 'parking', cold_rent: 50, status: 'vacant' });
  const futureUnit = await call('POST', '/units', { property_id: property.id, label: 'QA Künftige Einheit ' + suffix, unit_type: 'flat', cold_rent: 600, status: 'vacant' });
  const tenant = await call('POST', '/tenants', { full_name: 'QA Anna Beispiel ' + suffix, email: 'qol@example.test', phone: '+49 30 123456' });
  const year = new Date().getFullYear();
  const next = new Date(year, new Date().getMonth() + 1, 1);
  const local = value => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  const first = await call('POST', '/contracts', { property_id: property.id, unit_id: unit.id, tenant_id: tenant.id,
    contract_number: 'QA-1-' + suffix, start_date: `${year}-01-01`, end_date: local(next), status: 'terminated' });
  await call('POST', '/contracts', { property_id: property.id, unit_id: parking.id, tenant_id: tenant.id,
    contract_number: 'QA-2-' + suffix, start_date: `${year}-01-01`, status: 'active' });
  await call('POST', '/contracts', { property_id: property.id, unit_id: futureUnit.id, tenant_id: tenant.id,
    contract_number: 'QA-3-' + suffix, start_date: local(next), status: 'active' });
  [context, page] = await login('owner', process.env.QA_PASSWORD, user.id);
  await step('Property dossier: immediate key facts, retained tab on reload and browser Back', async () => {
    await page.goto(base.origin + '/properties/' + property.id);
    await expect(page.getByRole('heading', { name: property.name, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Aktive Verträge\s*2/ })).toBeVisible();
    assert.ok(await page.getByRole('heading', { name: property.name }).evaluate(element => element.getBoundingClientRect().top < 250));
    await page.getByRole('tab', { name: 'Einheiten (3)' }).click();
    await page.reload();
    await expect(page.getByRole('tab', { name: 'Einheiten (3)' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('link', { name: unit.label, exact: true }).click();
    await expect(page.getByRole('heading', { name: unit.label, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: tenant.full_name, exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('tab', { name: 'Einheiten (3)' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('button', { name: 'Als Favorit merken: ' + property.name, exact: true }).click();
    await expect(page.getByRole('button', { name: 'Favorit entfernen: ' + property.name, exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'property-1440.png') });
  });
  await step('Party list: multiple current units, direct contact links and current versus future tenancy', async () => {
    await page.goto(base.origin + '/tenants?suche=' + encodeURIComponent(tenant.full_name));
    await page.getByRole('button', { name: 'Alle 2 laufenden Verträge von ' + tenant.full_name + ' ansehen', exact: true }).click();
    const party = page.getByRole('dialog', { name: tenant.full_name, exact: true });
    await expect(party).toBeVisible();
    const current = party.locator('.party-contract-group').filter({ has: page.getByRole('heading', { name: 'Aktuelle Verträge', exact: true }) });
    await expect(current.getByRole('heading', { name: first.contract_number, exact: true })).toBeVisible();
    await expect(party.getByRole('heading', { name: 'Künftige Verträge', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'party-1440.png') });
    await page.keyboard.press('Escape');
    await expect(page.locator('a[href="mailto:qol@example.test"]')).toBeVisible();
    await expect(page.locator('a[href="tel:+4930123456"]')).toBeVisible();
    await page.getByRole('textbox', { name: /Mieter.*durchsuchen/ }).fill(parking.label);
    await expect(page.getByRole('button', { name: tenant.full_name, exact: true })).toBeVisible();
  });
  await step('Quick access: saved property, recent party, real dialog hand-off and keyboard focus return', async () => {
    const opener = page.getByRole('button', { name: 'Akten öffnen', exact: true });
    await opener.click();
    let dialog = page.getByRole('dialog', { name: 'Akten öffnen', exact: true });
    await expect(dialog.getByRole('link', { name: property.name + ' · Immobilie', exact: true }).first()).toBeVisible();
    await expect(dialog.getByRole('button', { name: tenant.full_name + ' · Partei', exact: true }).first()).toBeVisible();
    await page.screenshot({ path: path.join(output, 'quick-access-1440.png') });
    await dialog.getByRole('button', { name: tenant.full_name + ' · Partei', exact: true }).first().click();
    await expect(page.getByRole('dialog', { name: tenant.full_name, exact: true })).toBeVisible();
    await expect(dialog).toHaveCount(0);
    await page.keyboard.press('Escape');
    await opener.focus(); await page.keyboard.press('Alt+o');
    dialog = page.getByRole('dialog', { name: 'Akten öffnen', exact: true });
    await expect(dialog).toBeVisible(); await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
  });
  await step('Photos: controlled partial failure, original preview and explicit successful deletion', async () => {
    await page.goto(base.origin + '/properties/' + property.id);
    await page.getByText('Fotos der Immobilie', { exact: true }).click();
    let uploads = 0;
    const route = '**/api/v1/photos/upload?*';
    await page.route(route, async request => {
      if (++uploads === 2) await request.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'QA Datei absichtlich abgelehnt' }) });
      else await request.continue();
    });
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9xkAAAAASUVORK5CYII=', 'base64');
    await page.getByLabel('Fotos auswählen', { exact: true }).setInputFiles([
      { name: 'Haus.png', mimeType: 'image/png', buffer: png }, { name: 'Hof.png', mimeType: 'image/png', buffer: png },
    ]);
    await expect(page.getByRole('status').filter({ hasText: '1 von 2 Fotos gespeichert.' })).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'Hof.png' })).toBeVisible();
    const photos = await call('GET', `/photos?entity_type=property&entity_id=${property.id}`);
    assert.equal(photos.length, 1);
    await page.unroute(route);
    await page.getByRole('button', { name: 'Foto ansehen: Foto', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.screenshot({ path: path.join(output, 'photos-1440.png') });
    // Retain the photo until the independent reader has seen the same original.
    report.photo_id = photos[0].id;
  });
  await step('Two separate users: read-only photo preview, no mutation controls and private favorites', async () => {
    const name = 'qol_reader_' + suffix;
    const account = await call('POST', '/auth/users', { username: name, email: name + '@example.test', full_name: 'QA Lesender Benutzer',
      password: process.env.QA_PASSWORD, role: 'readonly', portfolio_access: 'selected', portfolio_ids: [portfolio.id] });
    const [readerContext, tab] = await login(name, process.env.QA_PASSWORD, account.id);
    reader = readerContext;
    await tab.goto(base.origin + '/properties/' + property.id);
    await tab.getByText('Fotos der Immobilie', { exact: true }).click();
    await expect(tab.getByRole('button', { name: 'Foto ansehen: Foto', exact: true })).toBeVisible();
    await expect(tab.getByRole('button', { name: 'Fotos hinzufügen', exact: true })).toHaveCount(0);
    await expect(tab.getByRole('button', { name: /Foto löschen/ })).toHaveCount(0);
    await tab.getByRole('button', { name: 'Akten öffnen', exact: true }).click();
    await expect(tab.getByRole('region', { name: 'Gemerkte Vorgänge' }).getByRole('link')).toHaveCount(0);
    await expect(tab.getByText(/Merken Sie Vorgänge direkt/)).toBeVisible();
    await tab.keyboard.press('Escape');
    await tab.getByRole('button', { name: 'Foto ansehen: Foto', exact: true }).click();
    await expect(tab.getByRole('dialog')).toBeVisible();
    await reader.close(); reader = null;
    await page.getByRole('button', { name: 'Foto löschen: Foto', exact: true }).click();
    const confirmation = page.getByRole('dialog');
    await confirmation.getByRole('button', { name: /Bestätigen|Löschen|Ja/, exact: false }).last().click();
    await expect(page.getByRole('status').filter({ hasText: 'Foto gelöscht.' })).toBeVisible();
    assert.equal((await call('GET', `/photos?entity_type=property&entity_id=${property.id}`)).length, 0);
  });
  await step('Mobile and keyboard: 320px and 360px without document overflow, reachable close and tab actions', async () => {
    for (const width of [320, 360]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base.origin + '/properties/' + property.id);
      await page.getByRole('tab', { name: 'Einheiten (3)' }).click();
      await page.getByRole('tab', { name: 'Einheiten (3)' }).press('ArrowRight');
      await expect(page.getByRole('tab', { name: 'Mieter & Verträge (2)' })).toHaveAttribute('aria-selected', 'true');
      await fitsViewport(page);
      await page.getByRole('button', { name: 'Akten öffnen', exact: true }).click();
      await expect(page.getByRole('dialog', { name: 'Akten öffnen', exact: true })).toBeVisible();
      await expect(page.getByRole('dialog', { name: 'Akten öffnen', exact: true }).getByRole('link', { name: property.name + ' · Immobilie', exact: true }).first()).toBeVisible();
      await expect(page.getByRole('dialog', { name: 'Akten öffnen', exact: true }).getByText('Wird geladen…', { exact: true })).toHaveCount(0);
      await fitsViewport(page);
      await page.screenshot({ path: path.join(output, `quick-access-${width}.png`) });
      await page.getByRole('button', { name: 'Aktenübersicht schließen', exact: true }).click();
    }
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const taskPrefix = 'QA Sortierung ' + suffix;
  const task2 = await call('POST', '/tasks', { title: taskPrefix + ' 2', due_date: '2030-01-02', status: 'open' });
  const task10 = await call('POST', '/tasks', { title: taskPrefix + ' 10', due_date: '2030-01-10', status: 'open' });
  await step('Actual task table: natural sorting, inclusive date filters, visible filter chips and complete CSV', async () => {
    await page.goto(base.origin + '/tasks');
    await page.getByRole('textbox', { name: 'Aufgaben durchsuchen', exact: true }).fill(taskPrefix);
    const table = page.getByRole('table', { name: 'Aufgaben', exact: true });
    await expect(table.locator('tbody tr')).toHaveCount(2);
    await table.getByRole('button', { name: 'Titel', exact: true }).click();
    await expect(table.locator('tbody tr').first()).toContainText(task2.title);
    await expect(table.locator('tbody tr').last()).toContainText(task10.title);
    await page.getByRole('button', { name: /^Filter/ }).click();
    await page.getByLabel('Fällig am: Von', { exact: true }).fill('2030-01-10');
    await page.getByLabel('Fällig am: Bis', { exact: true }).fill('2030-01-10');
    await expect(table.locator('tbody tr')).toHaveCount(1);
    await expect(table.locator('tbody tr')).toContainText(task10.title);
    await page.getByRole('button', { name: 'Filter entfernen: Fällig am', exact: true }).click();
    await expect(table.locator('tbody tr')).toHaveCount(2);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'CSV', exact: true }).click();
    const download = await downloadPromise;
    const exported = path.join(output, 'tasks.csv');
    await download.saveAs(exported);
    const csv = await fs.readFile(exported, 'utf8');
    assert.ok(csv.includes(task2.title) && csv.includes(task10.title));
    await page.screenshot({ path: path.join(output, 'task-filters-1440.png') });
  });
  await step('Actual bulk action: one rejected row remains selected, retry changes only that row', async () => {
    await page.getByRole('checkbox', { name: 'Auswählen: ' + task2.title, exact: true }).check();
    await page.getByRole('checkbox', { name: 'Auswählen: ' + task10.title, exact: true }).check();
    const route = '**/api/v1/tasks/' + task10.id;
    let rejected = 0;
    await page.route(route, async request => {
      if (request.request().method() === 'PATCH') {
        rejected++;
        await request.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'QA bewusster Teilfehler' }) });
      } else await request.continue();
    });
    const bulk = page.getByRole('region', { name: 'Auswahl', exact: true });
    await bulk.getByRole('button', { name: 'Erledigen', exact: true }).click();
    await expect(bulk.getByRole('alert')).toContainText('QA bewusster Teilfehler');
    await expect(page.getByRole('checkbox', { name: 'Auswählen: ' + task2.title, exact: true })).not.toBeChecked();
    await expect(page.getByRole('checkbox', { name: 'Auswählen: ' + task10.title, exact: true })).toBeChecked();
    assert.equal((await call('GET', '/tasks/' + task2.id)).status, 'completed');
    assert.equal((await call('GET', '/tasks/' + task10.id)).status, 'open');
    assert.equal(rejected, 1);
    await page.screenshot({ path: path.join(output, 'bulk-partial-failure-1440.png') });
    await page.unroute(route);
    await bulk.getByRole('button', { name: 'Erledigen', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/tasks/' + task10.id)).status).toBe('completed');
    await expect(page.getByRole('checkbox', { name: 'Auswählen: ' + task10.title, exact: true })).not.toBeChecked();
  });
  await step('Actual form: field-specific save failure, server draft recovery, protected discard and successful retry', async () => {
    await page.getByRole('button', { name: 'Neu', exact: true }).click();
    let form = page.getByRole('dialog', { name: 'Aufgabe erstellen', exact: true });
    const title = 'QA Entwurf ' + suffix;
    await expect(form.getByLabel('Titel', { exact: false })).toBeEnabled();
    await form.getByLabel('Titel', { exact: false }).fill(title);
    await form.getByLabel('Beschreibung', { exact: true }).fill('Diesen Text nach dem Neuladen erhalten.');
    const route = '**/api/v1/tasks';
    await page.route(route, async request => {
      if (request.request().method() === 'POST') await request.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [
        { loc: ['body', 'title'], msg: 'QA Titel bitte prüfen', type: 'value_error' },
      ] }) });
      else await request.continue();
    });
    await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(form.getByRole('alert').filter({ hasText: 'Ihre Eingaben bleiben erhalten' })).toBeFocused();
    await expect(form.getByLabel('Titel', { exact: false })).toHaveAttribute('aria-invalid', 'true');
    await form.getByRole('button', { name: 'Eingaben prüfen', exact: true }).click();
    await expect(form.getByLabel('Titel', { exact: false })).toBeFocused();
    await expect.poll(async () => (await call('GET', '/workspace/drafts?context=tasks')).items.some(d => d.values?.title === title)).toBe(true);
    page.once('dialog', dialog => dialog.accept());
    await page.reload();
    await page.getByRole('button', { name: 'Neu', exact: true }).click();
    form = page.getByRole('dialog', { name: 'Aufgabe erstellen', exact: true });
    await form.getByRole('button', { name: 'Entwurf verwerfen', exact: true }).click();
    await expect(form.getByRole('group', { name: 'Entwurf verwerfen bestätigen', exact: true })).toBeVisible();
    await form.getByRole('button', { name: 'Entwurf behalten', exact: true }).click();
    await form.getByRole('button', { name: 'Entwurf wiederaufnehmen', exact: true }).click();
    await expect(form.getByLabel('Titel', { exact: false })).toHaveValue(title);
    await expect(form.getByLabel('Titel', { exact: false })).toBeFocused();
    await expect(form.getByLabel('Beschreibung', { exact: true })).toHaveValue('Diesen Text nach dem Neuladen erhalten.');
    await page.screenshot({ path: path.join(output, 'recovered-form-1440.png') });
    await page.unroute(route);
    await form.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(form).toHaveCount(0);
    const success = page.locator('.toast-success').filter({ hasText: 'Aufgabe gespeichert' });
    await expect(success).toBeVisible();
    await success.hover();
    await success.getByRole('button').focus();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(4500); // Must outlive the ordinary four-second dismissal.
    await expect(success).toBeVisible();
    await success.getByRole('button').press('Enter');
    await expect(success).toHaveCount(0);
    const savedTasks = await call('GET', '/tasks?limit=100');
    assert.ok(Array.isArray(savedTasks));
    assert.equal(savedTasks.filter(task => task.title === title).length, 1);
    assert.ok(!(await call('GET', '/workspace/drafts?context=tasks')).items.some(d => d.values?.title === title));
  });
  await step('Actual notification inbox: bulk archive requires confirmation and preserves source tasks', async () => {
    const notice = await call('POST', '/notifications', { notification_type: 'task_due', title: 'QA Sammelhinweis ' + suffix,
      content: 'Nur persönlicher Empfangsbeleg', entity_type: 'task', entity_id: task2.id });
    await page.goto(base.origin + '/notifications');
    await expect(page.getByRole('heading', { name: 'Benachrichtigungen', exact: true })).toBeVisible();
    const inbox = page.getByRole('region', { name: 'Persönliche Benachrichtigungen', exact: true });
    const opener = inbox.getByRole('button', { name: 'Alle berechtigten Hinweise gelesen archivieren', exact: true });
    await opener.click();
    const confirmation = inbox.getByRole('group', { name: 'Sammelbestätigung', exact: true });
    await expect(confirmation.getByRole('button', { name: 'Abbrechen', exact: true })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    assert.ok((await call('GET', '/notifications/inbox?status=unread')).items.some(n => n.id === notice.id));
    await opener.click();
    await confirmation.getByRole('button', { name: /(?:Einen Hinweis|\d+ Hinweise) jetzt archivieren/ }).click();
    await expect.poll(async () => (await call('GET', '/notifications/inbox?status=archived')).items.some(n => n.id === notice.id)).toBe(true);
    assert.equal((await call('GET', '/notifications/' + notice.id)).status, 'unread');
    assert.equal((await call('GET', '/tasks/' + task2.id)).status, 'completed');
    await inbox.getByLabel('Ansicht', { exact: true }).selectOption('archived');
    await expect(inbox.getByRole('link', { name: 'QA Sammelhinweis ' + suffix, exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'inbox-archive-1440.png') });
    for (const width of [320, 360]) {
      await page.setViewportSize({ width, height: 900 });
      await fitsViewport(page);
      await expect(inbox.getByLabel('Ansicht', { exact: true })).toBeVisible();
      await page.screenshot({ path: path.join(output, `inbox-archive-${width}.png`) });
    }
  });
  assert.deepEqual(report.page_errors, []);
  assert.deepEqual(report.external, []);
} finally {
  await context?.close(); await reader?.close(); await api?.dispose(); await browser.close();
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
