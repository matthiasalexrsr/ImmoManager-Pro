import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { turnoverJourney } from './integration_process_qa.mjs';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic instance required');
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
const fixture = JSON.parse(await fs.readFile(path.join(output, 'fixture.json'), 'utf8'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const report = { synthetic_only: true, checks: [], page_errors: [], server_errors: [], external: [], portal_internal_requests: [] };
const browser = await chromium.launch({ headless: true });
const contexts = [];
let api, page, current = 'setup';
async function call(method, route, data, client = api) {
  const response = await client.fetch(base.origin + '/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${(await response.text()).slice(0, 800)}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, operation) {
  current = name;
  try { await operation(); report.checks.push({ name, ok: true }); console.log('PASS ' + name); }
  catch (error) {
    report.checks.push({ name, ok: false, error: String(error) });
    if (page) { await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); await fs.writeFile(path.join(output, 'failure.html'), await page.content()); }
    throw error;
  } finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function context(portal = false) {
  const result = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  contexts.push(result);
  await result.route('**/*', route => {
    const target = new URL(route.request().url());
    if (['http:', 'https:'].includes(target.protocol) && target.origin !== base.origin) {
      report.external.push(target.origin + target.pathname); return route.abort('blockedbyclient');
    }
    if (portal && target.pathname.startsWith('/api/') && !target.pathname.startsWith('/api/v1/portal/') && target.pathname !== '/api/v1/legal') report.portal_internal_requests.push(target.pathname);
    return route.continue();
  });
  result.on('page', p => {
    p.setDefaultTimeout(25000);
    p.on('pageerror', error => report.page_errors.push({ current, error: String(error) }));
    p.on('response', r => { if (r.status() >= 500 && new URL(r.url()).origin === base.origin) report.server_errors.push({ current, path: new URL(r.url()).pathname, status: r.status() }); });
  });
  return result;
}
async function login(name) {
  const setup = await request.newContext();
  const response = await setup.post(base.origin + '/api/v1/auth/login', { data: { username: name, password: process.env.QA_PASSWORD } });
  assert.ok(response.ok()); const token = (await response.json()).access_token;
  await setup.dispose();
  return request.newContext({ extraHTTPHeaders: { Authorization: 'Bearer ' + token } });
}
async function internalPage(name, client) {
  const who = await call('GET', '/auth/me', undefined, client);
  const ctx = await context();
  await ctx.addInitScript(({ id, origin }) => {
    if (window.top !== window || location.origin !== origin) return;
    localStorage.setItem('locale', 'de-DE'); localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, { id: who.id, origin: base.origin });
  const p = await ctx.newPage();
  await p.goto(base.origin + '/login');
  await p.getByRole('textbox', { name: /Benutzername/ }).fill(name);
  await p.locator('input[type=password]').fill(process.env.QA_PASSWORD);
  await p.locator('form button[type=submit]').click();
  await p.waitForURL(url => url.pathname === '/');
  return p;
}
async function fits(p = page) {
  const dimensions = await p.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(dimensions.document <= dimensions.viewport + 1, `Horizontal overflow: ${JSON.stringify(dimensions)}`);
}
async function shot(name, p = page) { await fits(p); await p.screenshot({ path: path.join(output, name + '.png') }); }
async function download(p, button, name) {
  const event = p.waitForEvent('download'); await button.click(); const result = await event;
  const target = path.join(output, name); await result.saveAs(target); assert.equal(await result.failure(), null); return fs.readFile(target);
}
const ph = { Origin: base.origin, 'X-Portal-Client': 'web-v1' };
const portalPassword = 'PortalBrowser-2026!';
try {
  api = await login('owner'); page = await internalPage('owner', api);
  const office = page;
  await step('CSV templates, six-file preview, field mapping, no business writes before commit, totals and confirmed import', async () => {
    const before = await call('GET', '/units?limit=1000');
    await page.goto(base.origin + '/settings?section=migration');
    const panel = page.getByRole('region', { name: 'Datenübernahme mit geprüfter Vorschau' });
    await download(page, panel.getByRole('button', { name: 'CSV-Vorlagen und Anleitung herunterladen' }), 'templates.zip');
    await panel.getByLabel('Quellsystem / stabiler Importname').fill('QA Browsermigration');
    await panel.getByLabel('Zielbestand für CSV').selectOption(fixture.portfolio.id);
    await panel.getByLabel('Dateien (bis sechs CSV-Dateien, ein Snapshot oder Kundenexport)').setInputFiles(fixture.csv.map(name => path.join(output, name)));
    await panel.getByRole('button', { name: 'Vorschau erstellen', exact: true }).click();
    await expect(panel.getByRole('heading', { name: 'Übernahme: QA Browsermigration' })).toBeFocused();
    await expect(panel.getByText('Bereit zur Bestätigung', { exact: true })).toBeVisible();
    assert.equal((await call('GET', '/units?limit=1000')).length, before.length);
    await expect(panel).toContainText('1234.56'); await expect(panel).toContainText('123.45');
    await panel.getByText('Feldzuordnung: units.csv', { exact: true }).click();
    await expect(panel.locator('details').filter({ hasText: 'Feldzuordnung: units.csv' }).getByLabel('property_ref (Pflicht)')).toHaveValue('property_ref');
    await panel.getByLabel('Prüfvermerk', { exact: true }).fill('Alle sechs Dateien, Referenzen und Kontrollsummen geprüft.');
    const warning = panel.getByLabel('Hinweise und mögliche Dubletten geprüft');
    if (await warning.isVisible()) await warning.check();
    await panel.getByLabel('Zuordnungen, Mengen und Beträge mit der Quelle abgeglichen').check();
    await panel.getByRole('button', { name: 'Übernahme verbindlich bestätigen' }).click();
    await expect(panel.getByText(/Die bestätigte Übernahme wurde gemeinsam gespeichert/)).toBeVisible();
    assert.equal((await call('GET', '/units?limit=1000')).length, before.length + 1);
    await shot('migration-desktop');
    await page.setViewportSize({ width: 390, height: 844 }); await shot('migration-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 });
  });

  const invitations = [];
  await step('Internal verified invitations are bound to two different households in the same building', async () => {
    await page.goto(base.origin + '/settings?section=portal');
    await page.getByText('Geprüfte Partei einladen', { exact: true }).click();
    for (const household of fixture.households) {
      await page.getByLabel('Geprüftes Verhältnis').selectOption(household.contract.id);
      await expect(page.getByLabel('Persönliche E-Mail-Adresse', { exact: true })).toHaveValue(household.tenant.email);
      await page.getByLabel('Dokumentierte Identitäts- und Verhältnisprüfung').fill('Persönliche Identität und Mietvertrag anhand der Unterlagen geprüft.');
      await page.getByRole('button', { name: 'Einladungslink erstellen' }).click();
      const link = page.getByLabel('Einmalig angezeigter Einladungslink');
      await expect(link).toHaveValue(/\/portal\/accept#/); invitations.push(await link.inputValue());
      await page.getByRole('button', { name: 'Linkanzeige schließen' }).click();
    }
  });
  const portals = [];
  await step('Invitation acceptance, one-time link, isolated portal contexts and keyboard focus', async () => {
    for (const invitation of invitations) {
      const ctx = await context(true), p = await ctx.newPage(); page = p;
      await p.goto(invitation);
      await expect(p.getByRole('heading', { name: 'Einladung annehmen' })).toBeVisible();
      assert.equal(new URL(p.url()).hash, '');
      await p.getByLabel('Passwort', { exact: true }).fill(portalPassword);
      await p.getByRole('button', { name: 'Einladung annehmen' }).click();
      await expect(p.getByRole('heading', { name: 'Meine Unterlagen und Anliegen' })).toBeFocused();
      await expect(p.getByText('Keine freigegebenen Dokumente für diese Suche vorhanden.')).toBeVisible();
      const me = await ctx.request.get(base.origin + '/api/v1/portal/me', { headers: ph }); assert.ok(me.ok());
      const repeat = await ctx.request.post(base.origin + '/api/v1/portal/accept', { headers: ph,
        data: { token: invitation.split('#')[1], password: portalPassword } }); assert.equal(repeat.status(), 401);
      portals.push({ ctx, p, me: await me.json() });
      const cookies = await ctx.cookies();
      assert.ok(cookies.every(c => c.httpOnly && c.path === '/api/v1/portal' && c.sameSite === 'Strict'));
      assert.equal(await p.evaluate(() => localStorage.getItem('token')), null);
    }
  });

  let publication;
  await step('Explicit immutable document publication, exact bytes, preview and foreign-ID denial on every transport', async () => {
    page = office;
    await page.getByRole('button', { name: 'Aktuellen Stand laden' }).click();
    const access = page.locator('li').filter({ hasText: fixture.households[0].tenant.email }).filter({ has: page.getByRole('button', { name: 'Zugang und Freigaben verwalten' }) });
    await access.getByRole('button', { name: 'Zugang und Freigaben verwalten' }).click();
    await expect(page.getByRole('heading', { name: 'Zugang: ' + fixture.households[0].tenant.email })).toBeFocused();
    await page.getByLabel('Passende Originalfassung').selectOption(fixture.households[0].version.id);
    await page.getByLabel('Im Portal sichtbarer Titel').fill('Nur Haushalt Eins: Vertragsunterlage');
    await page.getByLabel('Grund und Prüfung der Veröffentlichung').fill('Exakte Vertragsfassung persönlich für diese Partei geprüft.');
    await page.getByRole('button', { name: 'Diese Fassung für diese Partei veröffentlichen' }).click();
    const first = portals[0], second = portals[1]; page = first.p;
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Nur Haushalt Eins: Vertragsunterlage' })).toBeVisible();
    const bytes = await download(page, page.getByRole('button', { name: 'Herunterladen', exact: true }), 'portal-original.pdf');
    assert.equal(hash(bytes), fixture.households[0].sha256);
    const list = await first.ctx.request.get(base.origin + '/api/v1/portal/me/documents', { headers: ph });
    publication = (await list.json()).items[0];
    for (const suffix of ['download', 'preview']) {
      const route = base.origin + `/api/v1/portal/me/documents/${publication.id}/${suffix}`;
      const own = await first.ctx.request.get(route, { headers: ph }); assert.equal(own.status(), 200); assert.equal(hash(await own.body()), fixture.households[0].sha256);
      assert.equal((await second.ctx.request.get(route, { headers: ph })).status(), 404);
    }
    await second.p.reload(); await expect(second.p.getByText('Keine freigegebenen Dokumente für diese Suche vorhanden.')).toBeVisible();
    await download(page, page.getByRole('button', { name: 'Eigene Unterlagen exportieren' }), 'portal-export.zip');
    await page.getByLabel('Dokumenttitel suchen').fill('Haushalt Eins'); await page.getByRole('button', { name: 'Suchen', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Nur Haushalt Eins: Vertragsunterlage' })).toBeVisible();
    await shot('portal-documents-desktop');
  });

  let externalCase;
  await step('Portal damage with normalized picture, canonical maintenance link, private notes and two-way external communication', async () => {
    const first = portals[0]; page = first.p;
    await page.getByRole('button', { name: 'Schaden melden', exact: true }).click();
    await page.getByLabel('Kurzer Titel').fill('QA Wasserschaden am Fenster');
    await page.getByLabel('Was ist passiert?').fill('Nach Regen dringt Wasser am Rahmen ein. Bitte einen Termin abstimmen.');
    await page.getByLabel('Bilder (JPEG, PNG oder WebP; bis fünf, je 8 MiB, zusammen 20 MiB)').setInputFiles(path.join(output, 'damage.png'));
    await page.getByRole('button', { name: 'Schaden verbindlich melden' }).click();
    await expect(page.getByRole('heading', { name: 'QA Wasserschaden am Fenster', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Verlauf und Rückfragen öffnen' }).click();
    await expect(page.getByRole('heading', { name: 'QA Wasserschaden am Fenster', exact: true })).toBeFocused();
    await page.getByLabel('Ihre Nachricht', { exact: true }).fill('Ergänzung: Der Zugang ist morgen vormittags möglich.');
    await page.getByRole('button', { name: 'An die Verwaltung senden' }).click();
    await expect(page.getByText('Ergänzung: Der Zugang ist morgen vormittags möglich.', { exact: true })).toBeVisible();
    externalCase = (await call('GET', '/portal-admin/cases')).items[0];
    const internal = await call('GET', '/maintenance/' + externalCase.case_id);
    assert.equal(internal.property_id, fixture.property.id); assert.equal(internal.unit_id, fixture.households[0].unit.id);
    await call('PATCH', '/maintenance/' + externalCase.case_id, { description: 'INTERN: Nur für die Verwaltung, niemals im Portal.' });
    page = office; await page.goto(base.origin + `/maintenance/${externalCase.case_id}?tab=portal`);
    await page.getByRole('tab', { name: /Externe Kommunikation/ }).click();
    await page.getByRole('button', { name: 'Nachrichten öffnen' }).click();
    await page.getByLabel('Antwort an die externe Partei').fill('Wir bestätigen den Termin morgen um 10 Uhr.');
    await page.getByRole('button', { name: 'Antwort im Portal veröffentlichen' }).click();
    await expect(page.getByText('Wir bestätigen den Termin morgen um 10 Uhr.', { exact: true })).toBeVisible();
    await first.p.reload(); await first.p.getByRole('button', { name: 'Meine Anliegen', exact: true }).click();
    await first.p.getByRole('button', { name: 'Verlauf und Rückfragen öffnen' }).click();
    await expect(first.p.getByText('Wir bestätigen den Termin morgen um 10 Uhr.', { exact: true })).toBeVisible();
    await expect(first.p.getByText('INTERN: Nur für die Verwaltung, niemals im Portal.')).toHaveCount(0);
    assert.equal((await portals[1].ctx.request.get(base.origin + '/api/v1/portal/me/cases/' + externalCase.id, { headers: ph })).status(), 404);
    page = first.p; await shot('portal-case-desktop');
  });

  await step('Narrow screens, 200-percent layout, keyboard route and absence of internal portal data fetches', async () => {
    page = portals[0].p;
    await page.setViewportSize({ width: 390, height: 844 }); await shot('portal-mobile');
    await page.setViewportSize({ width: 720, height: 500 });
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; }); await shot('portal-large-text');
    await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.keyboard.press('Control+Home'); await page.keyboard.press('Tab');
    const focus = await page.evaluate(() => document.activeElement?.tagName); assert.ok(['A', 'BUTTON', 'INPUT', 'TEXTAREA'].includes(focus));
    assert.deepEqual(report.portal_internal_requests, []);
  });

  let invoice;
  await step('Real packaged XRechnung validation, readable original, durable job and atomic confirmed receipt', async () => {
    page = office; await page.goto(base.origin + '/invoice-review');
    await page.getByRole('tab', { name: 'E-Rechnungseingang' }).click();
    const intake = page.getByRole('region', { name: 'E-Rechnungseingang' });
    await intake.getByLabel(/^Immobilie/).selectOption(fixture.property.id);
    await intake.getByLabel('Originalbeleg (XML oder PDF, bis 25 MiB)').setInputFiles(fixture.invoice);
    await intake.getByRole('button', { name: 'Beleg einlesen', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'E-Rechnung prüfen und zuordnen' });
    await expect(dialog.getByRole('heading', { name: /Lesefassung/ })).toBeVisible({ timeout: 180000 });
    await expect(dialog.getByText(/^(Gültig|Mit Warnungen)$/).first()).toBeVisible({ timeout: 180000 });
    const original = await download(page, dialog.getByRole('button', { name: 'Original herunterladen' }), 'invoice-original.xml');
    assert.equal(hash(original), hash(await fs.readFile(fixture.invoice)));
    await download(page, dialog.getByRole('button', { name: 'Vollständigen Prüfbericht herunterladen' }), 'invoice-validation.xml');
    await dialog.getByLabel('Einheit (optional)').selectOption(fixture.households[0].unit.id);
    const warnings = dialog.getByLabel('Ich habe die Warnungen fachlich geprüft.');
    if (await warnings.isVisible()) {
      await warnings.check();
      await dialog.getByLabel('Begründung zur Übernahme trotz Warnungen').fill('Warnungen des offiziellen synthetischen Beispiels einzeln geprüft und dokumentiert.');
    }
    await dialog.getByRole('button', { name: 'Zuordnung bestätigen und übernehmen' }).click();
    await dialog.getByRole('link', { name: 'Rechnungsprüfung öffnen' }).click();
    invoice = (await call('GET', '/invoices?limit=1000')).find(row => row.document_id || row.invoice_number);
    assert.ok(invoice);
    assert.equal((await call('GET', `/invoices/${invoice.id}/review`)).review.unit_id, fixture.households[0].unit.id);
    await shot('invoice-review-desktop');
  });

  await step('Damage responsibility, accepted order, immutable performance evidence and invoice closure blockers', async () => {
    const route = '/maintenance/' + externalCase.case_id;
    await call('PATCH', route, { assignee: 'QA Verwaltung' });
    await call('POST', route + '/transition', { status: 'in_progress', reason: 'Zuständigkeit und Termin bestätigt.' });
    const quote = await call('POST', route + '/quotes', { supplier_name: 'QA Geprüfter Lieferant',
      quote_date: '2026-10-26', net_amount: invoice.net_amount, gross_amount: invoice.gross_amount });
    const order = await call('POST', route + '/quotes/' + quote.id + '/accept', { order_number: 'QA-ORDER-1' });
    const blocked = await api.post(base.origin + '/api/v1' + route + '/transition', { data: { status: 'completed' } });
    assert.equal(blocked.status(), 409);
    const protocol = await call('POST', route + '/protocols', { protocol_type: 'acceptance', protocol_date: '2026-10-26',
      participants: 'QA Verwaltung und Lieferant', result: 'accepted', order_id: order.id, defects: [], photo_ids: [] });
    const finished = await call('POST', route + '/protocols/' + protocol.id + '/finalize', { idempotency_key: randomUUID() });
    assert.equal(finished.status, 'final'); assert.ok(finished.content_sha256);
    await call('POST', route + '/orders/' + order.id + '/invoices', { invoice_id: invoice.id });
    const missingReview = await api.post(base.origin + '/api/v1' + route + '/transition', { data: { status: 'completed' } });
    assert.equal(missingReview.status(), 409);
    const work = await call('GET', '/work-center/items?kind=maintenance');
    assert.equal(work.items.find(row => row.entity_id === externalCase.case_id).workflow.stage, 'invoice_review');
    page = office; await page.goto(base.origin + '/maintenance/' + externalCase.case_id);
    await expect(page.getByRole('heading', { name: 'QA Wasserschaden am Fenster', exact: true })).toBeVisible();
    await shot('damage-order-and-proof');
    await page.goto(base.origin + '/invoice-review/' + invoice.id);
  });

  await step('Invoice checks, query, second-person approval, versioned bank recipient and payment proposal', async () => {
    page = office;
    await page.getByRole('region', { name: 'Sachliche Prüfung', exact: true }).getByLabel('Begründung').fill('Leistung und Zuordnung anhand der Originalunterlage geprüft.');
    await page.getByRole('region', { name: 'Sachliche Prüfung', exact: true }).getByRole('button', { name: 'Bestätigen', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/review`)).review.factual_result).toBe('confirmed');
    for (const box of await page.getByRole('region', { name: 'Rechnerische Prüfung', exact: true }).locator('input[type=checkbox]:enabled').all()) await box.check();
    await page.getByRole('region', { name: 'Rechnerische Prüfung', exact: true }).getByLabel('Begründung').fill('Steuergruppen und Summen mit dem strukturierten Original abgeglichen.');
    await page.getByRole('region', { name: 'Rechnerische Prüfung', exact: true }).getByRole('button', { name: 'Bestätigen', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/review`)).review.arithmetic_result).toBe('confirmed');
    await page.getByRole('region', { name: 'Entscheidung', exact: true }).getByLabel('Begründung', { exact: true }).fill('Rückfrage zum Leistungstermin vor abschließender Entscheidung.');
    await page.getByRole('region', { name: 'Entscheidung', exact: true }).getByRole('button', { name: 'Rückfrage', exact: true }).click();
    await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/review`)).review.status).toBe('query');
    await page.getByRole('button', { name: 'Bankdatenprüfung öffnen' }).click();
    await page.locator('#bankfreigabe summary').filter({ hasText: /Empfänger/ }).click();
    await page.getByLabel('Kontoinhaber', { exact: true }).fill('QA Geprüfter Lieferant');
    await page.getByLabel('IBAN', { exact: true }).fill('DE89370400440532013000');
    await page.getByLabel('Grund und Quelle der Bankangaben').fill('Unabhängig geprüfte Kontodaten aus dem Lieferantenstamm.');
    await page.getByRole('button', { name: 'Neue Empfängerversion speichern' }).click();
    await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/payment-authorization`)).recipient?.name).toBe('QA Geprüfter Lieferant');
    const manager = await login('verwalter');
    try {
      page = await internalPage('verwalter', manager);
      await page.goto(base.origin + `/invoice-review/${invoice.id}#bankfreigabe`);
      await page.getByRole('region', { name: 'Entscheidung', exact: true }).getByLabel('Begründung', { exact: true }).fill('Rückfrage beantwortet, Leistungstermin und Beleg bestätigt.');
      await page.getByRole('region', { name: 'Entscheidung', exact: true }).getByRole('button', { name: 'Freigeben', exact: true }).click();
      await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/review`)).review.status).toBe('approved');
      await office.reload();
      await office.getByRole('button', { name: 'Bankdatenprüfung öffnen' }).click();
      await expect(office.getByRole('button', { name: 'Diesen Betrag und Empfänger freigeben' })).toBeDisabled();
      await page.getByLabel('Dokumentierte Gegenprüfung').fill('Bekannte Lieferantennummer zurückgerufen; Kontoinhaber und IBAN bestätigt.');
      await page.getByLabel('Freigabebegründung').fill('Unabhängige Gegenprüfung der Bankverbindung abgeschlossen.');
      await page.getByRole('button', { name: 'Diesen Betrag und Empfänger freigeben' }).click();
      await expect.poll(async () => (await call('GET', `/invoices/${invoice.id}/payment-authorization`)).authorized).toBe(true);
      await shot('bank-four-eyes');
      await page.setViewportSize({ width: 390, height: 844 }); await shot('bank-mobile');
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(base.origin + '/invoice-review?tab=proposals');
      await expect(page.getByRole('link').filter({ hasText: invoice.invoice_number })).toBeVisible();
      const work = await call('GET', '/work-center/items?kind=invoice');
      assert.ok(work.items.some(row => row.entity_id === invoice.id && row.workflow.stage === 'proposal'));
    } finally { await manager.dispose(); }
  });

  await step('Documented damage closure, reopening and portal status follow the leading business record', async () => {
    const route = '/maintenance/' + externalCase.case_id;
    await call('POST', route + '/transition', { status: 'completed', reason: 'Abnahme und geprüfte Rechnung vollständig dokumentiert.' });
    assert.equal((await call('GET', route)).status, 'completed');
    const portal = await portals[0].ctx.request.get(base.origin + '/api/v1/portal/me/cases/' + externalCase.id, { headers: ph });
    assert.equal(portal.status(), 200);
    const visible = await portal.json(); assert.ok(JSON.stringify(visible).includes('completed'));
    assert.ok(!JSON.stringify(visible).includes('INTERN:'));
    await call('POST', route + '/transition', { status: 'in_progress', reason: 'Wiederaufnahme zur dokumentierten Nachkontrolle.' });
    assert.equal((await call('GET', route)).status, 'in_progress');
    await call('POST', route + '/transition', { status: 'completed', reason: 'Nachkontrolle abgeschlossen, Belege bleiben unverändert erhalten.' });
  });

  await step('Complete tenant change: handover, meter, reletting contract and documented deposit release', async () => {
    page = office;
    await turnoverJourney({ page, api, call, base, fixture, expect, shot, download, hash });
  });

  await step('Customer export durable job and verified protected download', async () => {
    page = office; await page.goto(base.origin + '/settings?section=migration');
    const panel = page.getByRole('region', { name: 'Kundenexport', exact: true });
    await panel.getByRole('button', { name: 'Kundenexport erstellen' }).click();
    const button = panel.getByRole('button', { name: 'Exportpaket herunterladen' });
    await expect(button).toBeVisible({ timeout: 120000 });
    const bytes = await download(page, button, 'customer-export.zip');
    const latest = (await call('GET', '/data/portability-exports')).items[0]; assert.equal(hash(bytes), latest.sha256);
  });

  await step('Immediate grant revocation blocks old original, preview, cases and retained session', async () => {
    page = office; await page.goto(base.origin + '/settings?section=portal');
    const row = page.locator('li').filter({ hasText: fixture.households[0].tenant.email }).filter({ has: page.getByRole('button', { name: 'Zugang und Freigaben verwalten' }) });
    await row.getByRole('button', { name: 'Zugang und Freigaben verwalten' }).click();
    await page.getByLabel('Begründung für Änderung oder Widerruf').fill('Widerruf nach Ende des geprüften Testverhältnisses.');
    await page.getByRole('button', { name: 'Diese Zuordnung widerrufen', exact: true }).click();
    await expect.poll(async () => (await portals[0].ctx.request.get(base.origin + `/api/v1/portal/me/documents/${publication.id}/download`, { headers: ph })).status()).toBe(404);
    for (const route of [`/documents/${publication.id}/preview`, '/cases/' + externalCase.id]) {
      assert.equal((await portals[0].ctx.request.get(base.origin + '/api/v1/portal/me' + route, { headers: ph })).status(), 404);
    }
    await portals[0].p.reload(); await expect(portals[0].p.getByText('Derzeit ist keine aktive Zuordnung vorhanden. Bitte wenden Sie sich an Ihre Verwaltung.')).toBeVisible();
    assert.equal((await portals[1].ctx.request.get(base.origin + '/api/v1/portal/me', { headers: ph })).status(), 200);
  });

  await step('Verified password recovery invalidates an existing session and issues exactly one usable link', async () => {
    page = office;
    await page.getByText('Vergessenes Portalpasswort zurücksetzen', { exact: true }).click();
    await page.getByLabel('Erneute Identitätsprüfung dokumentieren').fill('Persönlichen Ausweis und bekannte Rückrufnummer unabhängig erneut geprüft.');
    await page.getByRole('button', { name: 'Zugang zurücksetzen und neuen Link erstellen' }).click();
    const link = page.getByLabel('Einmalig angezeigter Wiederherstellungslink');
    await expect(link).toHaveValue(/\/portal\/accept#/);
    const invitation = await link.inputValue();
    assert.equal((await portals[0].ctx.request.get(base.origin + '/api/v1/portal/me', { headers: ph })).status(), 401);
    page = portals[0].p; await page.goto(invitation);
    await page.getByLabel('Passwort', { exact: true }).fill('NewPortalBrowser2026!');
    await page.getByRole('button', { name: 'Einladung annehmen' }).click();
    await expect(page.getByRole('heading', { name: 'Meine Unterlagen und Anliegen' })).toBeFocused();
    const replay = await portals[0].ctx.request.post(base.origin + '/api/v1/portal/accept', { headers: ph,
      data: { token: invitation.split('#')[1], password: 'AnotherPortalBrowser2026!' } });
    assert.equal(replay.status(), 401);
  });

  await step('Privacy hold, immediate direct-file restriction, subject export and separate decision journal', async () => {
    page = office; await page.goto(base.origin + '/settings?section=privacy');
    const document = fixture.households[1].document;
    const file = new URL(document.file_url, base.origin).href;
    assert.equal((await api.get(file)).status(), 200);
    await page.getByRole('combobox', { name: /^Datensatz/ }).selectOption(document.id);
    await page.getByLabel('Begründung der Entscheidung').fill('Unterlage bleibt wegen des dokumentierten Aufbewahrungsgrundes erhalten.');
    await page.getByRole('button', { name: 'Aufbewahrung sperren', exact: true }).click();
    await expect(page.getByText(/Aufbewahrungssperre: Gesetzt/)).toBeVisible();
    await page.getByRole('button', { name: 'Veröffentlichung, Suche und KI sperren', exact: true }).click();
    await expect(page.getByText(/Verarbeitungssperre: Gesetzt/)).toBeVisible();
    assert.ok([403, 404].includes((await api.get(file)).status()));
    await shot('privacy-controls');
    await page.getByRole('button', { name: 'Auskunfts- und Löschanfragen', exact: true }).click();
    await page.getByLabel(/^Geprüfte Partei/).selectOption(fixture.households[0].tenant.id);
    await page.getByLabel('Bearbeitungsfrist').fill('2026-11-25');
    await page.getByLabel('Identitätsprüfung', { exact: true }).fill('Identität persönlich anhand des vorhandenen Vertrags und eines Ausweises geprüft.');
    await page.getByRole('button', { name: 'Anfrage erfassen', exact: true }).click();
    const bytes = await download(page, page.getByRole('button', { name: 'Auskunft zur Inhaltsprüfung herunterladen' }), 'subject-access.json');
    const subject = JSON.parse(bytes);
    assert.equal(subject.data.subject.id, fixture.households[0].tenant.id);
    assert.deepEqual(subject.data.extensions.portal_cases.map(row => row.id), [externalCase.id]);
    assert.ok(!bytes.toString().includes('password_hash'));
    await page.getByLabel('Begründung einschließlich zurückbehaltener Daten').fill('Auskunft zur persönlichen Inhaltsprüfung zusammengestellt; keine externe Übermittlung im Test.');
    await page.getByRole('button', { name: 'Entscheidung für diesen Prüfstand speichern' }).click();
    await expect(page.getByRole('heading', { name: /Teilweise erfüllt/ })).toBeVisible();
    await page.getByRole('button', { name: 'Journal und Wiederherstellung', exact: true }).click();
    const journal = JSON.parse(await download(page, page.getByRole('button', { name: 'Aktuelles Datenschutzjournal herunterladen' }), 'privacy-journal.json'));
    assert.equal(journal.format, 'immomanager-privacy-controls/1'); assert.ok(journal.controls.length > 0); assert.ok(journal.sha256);
  });

  await step('No browser exceptions, unexpected server errors or external requests', async () => {
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.server_errors, []); assert.deepEqual(report.external, []);
  });
} finally {
  await api?.dispose();
  for (const ctx of contexts) await ctx.close();
  await browser.close();
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
