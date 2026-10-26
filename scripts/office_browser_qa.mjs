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
const report = { synthetic_only: true, checks: [], pages: [], page_errors: [], server_errors: [], external: [], expected_errors: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let api, context, page;
let portfolioFailureExpected = false;
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
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
  assert.ok(size.document <= size.viewport + 1, `Page overflow ${JSON.stringify(size)}`);
}
try {
  const setup = await request.newContext({ baseURL: base.origin });
  const login = await setup.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(login.ok());
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: { Authorization: 'Bearer ' + (await login.json()).access_token } });
  await setup.dispose();
  const owner = await call('GET', '/auth/me');
  const portfolio = await call('POST', '/portfolios', { name: 'QA Büroabläufe' });
  const property = await call('POST', '/properties', { portfolio_id: portfolio.id, name: 'QA Bürohaus', property_type: 'residential' });
  const unit = await call('POST', '/units', { property_id: property.id, label: 'QA Bürowohnung', unit_type: 'flat' });
  const contact = await call('POST', '/contacts', { company_name: 'QA Kontakt', email: 'kontakt@example.test', contact_type: 'supplier' });
  const threadA = await call('POST', '/messages/threads', { subject: 'QA Konversation A', property_id: property.id, unit_id: unit.id, participant_ids: contact.id });
  const threadB = await call('POST', '/messages/threads', { subject: 'QA Konversation B', property_id: property.id });
  const task = await call('POST', '/tasks', { title: 'QA Büroaufgabe', property_id: property.id, status: 'open', due_date: '2026-11-01' });
  const connection = await call('POST', '/integration-connections', { idempotency_key: crypto.randomUUID(),
    provider_id: 'email', name: 'QA ohne externen Versand', enabled: true,
    config: { sender_email: 'verwaltung@example.test', smtp_host: 'smtp.invalid', smtp_use_tls: true } });
  const notice = await call('POST', '/notifications', { notification_type: 'task_due', title: 'QA Aufgabe öffnen',
    content: 'Die konkrete Büroaufgabe prüfen', entity_type: 'task', entity_id: task.id });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(id => { localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true })); }, owner.id);
  page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror', error => report.page_errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && /Content.Security.Policy/i.test(message.text())) report.page_errors.push(`CSP: ${message.text()}`); });
  page.on('response', response => {
    if (response.status() < 500) return;
    const row = { url: new URL(response.url()).pathname, status: response.status() };
    (portfolioFailureExpected && row.url === '/api/v1/portfolios' ? report.expected_errors : report.server_errors).push(row);
  });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && url.origin !== base.origin) { report.external.push(url.origin); return route.abort(); }
    return route.continue();
  });
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');

  await step('Failed portfolio reads cannot erase account access and can be retried inside the dialog', async () => {
    const reader = (await call('GET', '/auth/users')).find(user => user.role === 'readonly');
    assert.ok(reader);
    await call('PATCH', '/auth/users/' + reader.id, { portfolio_access: 'selected', portfolio_ids: [portfolio.id] });
    portfolioFailureExpected = true;
    await page.route('**/api/v1/portfolios*', route => route.fulfill({ status: 503, contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'SERVICE_UNAVAILABLE', message: 'QA Portfolios offline' } }) }));
    await page.goto(base.origin + '/settings?section=users');
    const account = page.locator('.data-table tbody tr').filter({ hasText: reader.username });
    await account.getByRole('button', { name: 'Portfolios', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeDisabled();
    await expect(dialog.getByRole('alert')).toContainText('QA Portfolios offline');
    assert.deepEqual((await call('GET', '/auth/users')).find(user => user.id === reader.id).portfolio_ids, [portfolio.id]);
    await page.unroute('**/api/v1/portfolios*');
    await dialog.getByRole('button', { name: 'Portfolios erneut laden', exact: true }).click();
    await expect(dialog.getByRole('checkbox', { name: portfolio.name, exact: true })).toBeChecked();
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    portfolioFailureExpected = false;
    assert.deepEqual((await call('GET', '/auth/users')).find(user => user.id === reader.id).portfolio_ids, [portfolio.id]);
  });

  await step('Work center edits due date and assignee with a durable undo', async () => {
    await page.goto(`${base.origin}/work-center?kind=task&property_id=${property.id}`);
    const item = page.locator('.work-item').filter({ hasText: task.title });
    await item.getByRole('button', { name: 'Fälligkeit bearbeiten: ' + task.title }).click();
    await item.getByLabel('Fälligkeit', { exact: true }).fill('2026-11-06');
    await item.locator('form').filter({ has: page.getByLabel('Fälligkeit', { exact: true }) }).getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/tasks/' + task.id)).due_date).toBe('2026-11-06');
    await expect(item.getByRole('button', { name: 'Zuständigkeit bearbeiten: ' + task.title })).toBeVisible();
    await item.getByRole('button', { name: 'Zuständigkeit bearbeiten: ' + task.title }).click();
    await item.getByLabel('Zuständigkeit', { exact: true }).fill('QA Verwaltung');
    await item.locator('form').filter({ has: page.getByLabel('Zuständigkeit', { exact: true }) }).getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/tasks/' + task.id)).assignee).toBe('QA Verwaltung');
    await page.getByRole('button', { name: 'Rückgängig', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/tasks/' + task.id)).assignee).toBe(null);
  });
  await step('Personal deferral changes the active work list and can be removed', async () => {
    const item = page.locator('.work-item').filter({ hasText: task.title });
    await item.getByRole('button', { name: 'Später bearbeiten' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Wieder anzeigen am', { exact: false }).fill('2099-01-01');
    await dialog.getByLabel('Notiz', { exact: false }).fill('QA nach Rücksprache bearbeiten');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page.getByLabel('Wiedervorlagen', { exact: true }).selectOption('active');
    await expect(item).toHaveCount(0);
    await page.getByLabel('Wiedervorlagen', { exact: true }).selectOption('');
    await item.getByRole('button', { name: 'Später bearbeiten' }).click();
    await dialog.getByLabel('Wiedervorlage', { exact: true }).selectOption('remove');
    await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
  });
  await step('Notification opens the actual task, archives a personal receipt and reopens from the archive', async () => {
    await page.goto(base.origin + '/notifications');
    await page.locator('.personal-inbox-page').getByRole('link', { name: notice.title, exact: true }).click();
    await expect(page.getByRole('heading', { name: task.title, exact: true })).toBeVisible();
    await expect.poll(async () => (await call('GET', '/notifications/inbox?status=archived')).items.some(item => item.id === notice.id)).toBe(true);
    await page.goto(base.origin + '/notifications?status=archived');
    const inbox = page.locator('.personal-inbox-page');
    await inbox.getByRole('button', { name: 'Wieder in den Eingang', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/notifications/inbox?status=unread')).items.some(item => item.id === notice.id)).toBe(true);
    await page.getByRole('button', { name: 'Benachrichtigungen', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Benachrichtigungs-Vorschau' }).getByRole('link', { name: notice.title, exact: true })).toBeVisible();
    await page.getByRole('region', { name: 'Benachrichtigungs-Vorschau' }).getByRole('link', { name: notice.title, exact: true }).click();
    await expect(page.getByRole('region', { name: 'Benachrichtigungs-Vorschau' })).toHaveCount(0);
  });
  await step('Notification filters follow the URL and browser back navigation', async () => {
    await page.goto(base.origin + '/notifications?status=archived&kind=task');
    const inbox = page.locator('.personal-inbox-page');
    await expect(inbox.getByLabel('Quelle', { exact: true })).toHaveValue('task');
    await inbox.getByLabel('Ansicht', { exact: true }).selectOption('unread');
    await expect(page).toHaveURL(/status=unread/);
    await page.goBack();
    await expect(inbox.getByLabel('Ansicht', { exact: true })).toHaveValue('archived');
  });
  await step('Settings resolve a real revision conflict without losing the personal draft', async () => {
    await page.goto(base.origin + '/settings');
    await page.getByLabel('Geltungsbereich', { exact: true }).selectOption('personal');
    await page.getByLabel('Suche nach Einstellung oder Bereich').fill('Erinnerungsvorlauf');
    const input = page.getByLabel('Erinnerungsvorlauf in Tagen', { exact: true });
    await input.fill('14');
    const catalogue = await call('GET', '/auth/users/me/settings');
    const original = catalogue.items.find(item => item.key === 'reminder_days' && item.scope === 'personal');
    await call('PUT', '/auth/users/me/settings', { values: { reminder_days: '10' }, scope: 'personal', base_revision: original.revision, idempotency_key: crypto.randomUUID() });
    const card = page.locator('.setting-card').filter({ has: input });
    await card.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect(card.getByText(/Aktuell gespeichert:/)).toContainText('10');
    await expect(input).toHaveValue('14');
    await card.getByRole('button', { name: /Mit aktuellem Stand vergleichen/ }).click();
    await card.getByRole('button', { name: 'Speichern', exact: true }).click();
    await expect.poll(async () => (await call('GET', '/auth/users/me/preferences')).reminder_days).toBe('14');
    await page.screenshot({ path: path.join(output, 'settings-1440.png') });
  });
  await step('Settings sections retain URLs, browser history and a valid fallback', async () => {
    await page.getByRole('button', { name: 'Sicherheit / MFA', exact: true }).click();
    await expect(page).toHaveURL(/section=security/);
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Einstellungen finden', exact: true })).toBeVisible();
    await page.goto(base.origin + '/settings?section=unknown');
    await expect(page.getByRole('heading', { name: 'Einstellungen finden', exact: true })).toBeVisible();
  });
  await step('Deep-linked conversations allow switching, private drafts and linked dossiers', async () => {
    await page.goto(`${base.origin}/messages?focus_id=${threadA.id}`);
    await expect(page.getByRole('heading', { name: threadA.subject, exact: true })).toBeVisible();
    const links = page.getByRole('navigation', { name: 'Verknüpfte Akten' });
    await expect(links.getByRole('link', { name: property.name })).toHaveAttribute('href', '/properties/' + property.id);
    await expect(links.getByRole('link', { name: unit.label })).toHaveAttribute('href', '/units?focus_id=' + unit.id);
    await expect(links.getByRole('link', { name: contact.company_name })).toHaveAttribute('href', '/contacts?focus_id=' + contact.id);
    await page.locator('.message-detail textarea').fill('QA interne Gesprächsnotiz');
    await page.locator('.message-item').filter({ hasText: threadB.subject }).click();
    await expect(page.getByRole('heading', { name: threadB.subject, exact: true })).toBeVisible();
    await expect(page.locator('.message-detail textarea')).toHaveValue('');
    await page.goBack();
    await expect(page.getByRole('heading', { name: threadA.subject, exact: true })).toBeVisible();
    await expect(page.locator('.message-detail textarea')).toHaveValue('QA interne Gesprächsnotiz');
    await page.locator('.message-detail').getByRole('button', { name: 'Senden', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/messages/threads/${threadA.id}/page`)).total).toBe(1);
  });
  await step('E-mail drafts freeze a preview without sending and retain their selection on refresh', async () => {
    await page.getByRole('button', { name: 'E-Mail und Empfang', exact: true }).click();
    const center = page.getByRole('region', { name: 'E-Mail und Empfang' });
    await center.getByLabel('Konversation', { exact: true }).selectOption(threadA.id);
    await center.getByLabel('E-Mail-Verbindung', { exact: true }).selectOption(connection.id);
    await center.getByLabel('An', { exact: true }).fill('empfang@example.test');
    await center.getByLabel('Betreff', { exact: true }).fill('QA Büro-E-Mail');
    await center.getByLabel('Nachricht', { exact: true }).fill('Geprüfter Entwurf. Keine externe Zustellung.');
    await center.getByRole('button', { name: 'Entwurf speichern', exact: true }).click();
    await expect(center.getByRole('heading', { name: 'Entwurf bearbeiten' })).toBeVisible();
    await center.getByRole('button', { name: 'Entwurf speichern und Vorschau einfrieren' }).click();
    await expect(center.getByText('Vorschau – noch nicht freigegeben', { exact: true }).last()).toBeVisible();
    const previews = await call('GET', `/messages/communication?kind=outbound&thread_id=${threadA.id}`);
    assert.equal(previews.items.length, 1); assert.equal(previews.items[0].state, 'preview');
    await center.getByRole('button', { name: 'Aktualisieren', exact: true }).click();
    await expect(center.getByRole('heading', { name: 'QA Büro-E-Mail', exact: true })).toBeVisible();
    assert.equal((await call('GET', `/messages/communication?kind=outbound&thread_id=${threadA.id}`)).items[0].state, 'preview');
    await page.screenshot({ path: path.join(output, 'communication-1440.png') });
  });
  await step('Work center, notifications, conversations and settings fit 320, 360 and 1440 pixels', async () => {
    const routes = ['/work-center', '/notifications?status=archived', `/messages?focus_id=${threadA.id}`, '/messages?view=communication',
      '/settings', '/settings?section=security', '/settings?section=system', '/settings?section=users'];
    for (const width of [320, 360, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const route of routes) {
        await page.goto(base.origin + route);
        await expect(route.startsWith('/notifications') ? page.getByRole('heading', { name: 'Persönlicher Eingang', exact: true })
          : page.getByRole('heading', { level: 1 }).first()).toBeVisible();
        await expect(page.locator('.page-loading')).toHaveCount(0);
        await page.waitForLoadState('networkidle');
        await fits(); report.pages.push({ route, width, ok: true });
        if (width === 320 && ['/work-center', '/settings'].includes(route)) await page.screenshot({ path: path.join(output, route.slice(1) + '-320.png') });
      }
    }
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.server_errors, []); assert.deepEqual(report.external, []);
    report.external_messages_sent = 0;
  });
} finally {
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  await context?.close(); await api?.dispose(); await browser.close();
}
