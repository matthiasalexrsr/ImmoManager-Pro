/** End-to-end interface preparation and objection decisions; owned synthetic server only. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const base = new URL(process.env.QA_BASE_URL || '');
if (base.hostname !== '127.0.0.1' || ['8000', '8765'].includes(base.port) || process.env.QA_ALLOW_TEST_WRITES !== '1') throw Error('Owned synthetic server required');
const fixture = JSON.parse(await fs.readFile(process.env.QA_INTERFACE_FIXTURE, 'utf8'));
const module = pathToFileURL(process.env.QA_PLAYWRIGHT_PATH);
const { chromium, request } = await import(module.href);
const { expect } = await import(new URL('./test.mjs', module).href);
const output = process.env.QA_OUTPUT;
await fs.mkdir(output, { recursive: true });
const report = { synthetic_only: true, checks: [], page_errors: [], external: [] };
const browser = await chromium.launch({ headless: true,
  ...(process.env.QA_CHROMIUM_EXECUTABLE ? { executablePath: process.env.QA_CHROMIUM_EXECUTABLE } : {}) });
let context, page, api;
async function call(method, route, data) {
  const response = await api.fetch('/api/v1' + route, { method, data });
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}
async function step(name, action) {
  try { await action(); report.checks.push({ name, ok: true }); }
  catch (e) { report.checks.push({ name, ok: false, error: String(e) }); await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); throw e; }
  finally { await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); }
}
async function fits() {
  const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(size.document <= size.viewport + 1, JSON.stringify(size));
}
async function download(button, filename) {
  const pending = page.waitForEvent('download');
  await button.click();
  const value = await pending;
  assert.equal(await value.failure(), null);
  const file = path.join(output, filename);
  await value.saveAs(file);
  return fs.readFile(file);
}
try {
  const bootstrap = await request.newContext({ baseURL: base.origin });
  const response = await bootstrap.post('/api/v1/auth/login', { data: { username: 'owner', password: process.env.QA_PASSWORD } });
  assert.ok(response.ok());
  const headers = { Authorization: 'Bearer ' + (await response.json()).access_token };
  api = await request.newContext({ baseURL: base.origin, extraHTTPHeaders: headers });
  await bootstrap.dispose();
  const user = await call('GET', '/auth/me');
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (/^https?:$/.test(url.protocol) && url.origin !== base.origin) {
      report.external.push(url.origin + url.pathname);
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  await context.addInitScript(id => {
    localStorage.setItem('locale', 'de-DE');
    localStorage.setItem('immo.tutorial.' + id, JSON.stringify({ offered: true }));
  }, user.id);
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => report.page_errors.push(String(error)));
  await page.goto(base.origin + '/login');
  await page.locator('input[autocomplete="username"]').fill('owner');
  await page.locator('input[type="password"]').fill(process.env.QA_PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL(url => url.pathname === '/');

  await step('TEHA: current evidence is visible and local cost/follow-up packets download without dispatch', async () => {
    await page.goto(base.origin + '/teha?connection=' + fixture.teha_connection);
    await expect(page.getByRole('heading', { name: 'Portalvertrag und Nachweise', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Lokales Prüfpaket herunterladen', exact: true })).toHaveCount(2);
    const rows = await call('GET', `/teha/${fixture.teha_connection}/returns`);
    for (const [index, row] of rows.items.entries()) {
      const bytes = await download(page.getByRole('button', { name: 'Lokales Prüfpaket herunterladen', exact: true }).nth(index), `teha-packet-${index}.json`);
      const packet = JSON.parse(bytes.toString('utf8'));
      assert.equal(packet.id, row.id);
      assert.equal(packet.snapshot_sha256, row.snapshot_sha256);
      assert.equal(packet.portal_evidence.external_write_enabled, false);
      assert.equal(packet.portal_evidence.source_sha256, '328ac6c642b9892e7604ee67cf4e3c0d83b0b5f8700795561ec01b7b94bfa618');
      assert.ok(packet.validation.local_valid);
      if (packet.snapshot.kind === 'cost_user_data') assert.equal(packet.validation.summary.total_decimal, '0.30');
      else {
        assert.equal(packet.snapshot.portal_preview.payload.Altauftrag, 501);
        assert.equal(packet.snapshot.portal_preview.payload.Nutzer[0].Id, 23);
      }
    }
    await fits();
    await page.screenshot({ path: path.join(output, 'teha-review-1440.png') });
  });
  await step('TEHA: document original request is prepared from its directory row with exact source identity', async () => {
    await page.goto(base.origin + `/teha?connection=${fixture.teha_connection}&batch=${fixture.teha_directory_batch}`);
    await page.getByRole('button', { name: /^QA Dokumentverzeichnis\.pdf ·/ }).click();
    await page.getByRole('button', { name: 'Originalempfang vorbereiten', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Lesenden Empfang ausdrücklich starten', exact: true })).toBeVisible();
    const runs = await call('GET', `/integration-connections/${fixture.teha_connection}/runs`);
    const prepared = runs.items.find(row => row.state === 'prepared' && row.action === 'document');
    assert.ok(prepared, 'Prepared document run, no network dispatch');
    await page.setViewportSize({ width: 320, height: 900 });
    await fits();
    await page.screenshot({ path: path.join(output, 'teha-review-320.png') });
  });
  await step('WISO: retained manual worksheet, exact monetary sources and actual neutral ZIP download', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base.origin + '/tax-exports');
    await page.locator('.tax-exports').getByRole('combobox', { name: /^Portfolio/ }).selectOption(fixture.wiso_portfolio);
    await page.getByRole('button', { name: 'Gesicherten Übertragungsbogen prüfen', exact: true }).click();
    await expect(page.getByText(/Übertragungsbogen enthält offene Punkte/)).toBeVisible();
    const report = await call('GET', `/reports/annual-tax/projections/${fixture.wiso_projection}/wiso-preparation`);
    assert.equal(report.vendor_file_ready, false);
    assert.equal(report.target_import_verified, false);
    assert.equal(report.mapped_totals.income_cents, '10000');
    assert.equal(report.mapped_totals.expense_cents, '2009');
    assert.ok(report.issues.some(row => row.code === 'partial_year'));
    const bytes = await download(page.getByRole('button', { name: 'Neutrale Quellen und manuellen Übertragungsbogen herunterladen', exact: true }), 'wiso-manual-sources.zip');
    const apiDownload = await api.get(`/api/v1/reports/annual-tax/projections/${fixture.wiso_projection}/download`);
    assert.ok(apiDownload.ok());
    assert.deepEqual(bytes, await apiDownload.body());
    assert.equal(bytes.subarray(0, 2).toString(), 'PK');
    await fits();
    await page.screenshot({ path: path.join(output, 'wiso-manual-1440.png') });
    await page.setViewportSize({ width: 360, height: 900 });
    await fits();
    await page.screenshot({ path: path.join(output, 'wiso-manual-360.png') });
  });

  const pdfs = [];
  for (const id of fixture.statement_ids) {
    const value = await api.get(`/api/v1/billing/statements/${id}/pdf`);
    assert.ok(value.ok()); pdfs.push(await value.body());
  }
  const reason = 'QA Einwand gegen die Flächenzuordnung';
  await step('Objection: actual date and individual statement are captured in the browser', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base.origin + '/statements?period_id=' + fixture.billing_period);
    await expect(page.getByRole('row').nth(1)).toContainText('Haus A');
    await page.getByRole('row').nth(1).focus();
    await page.keyboard.press('Enter');
    await page.getByRole('button', { name: 'Widerspruch', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Widerspruch erfassen', exact: true });
    await dialog.getByLabel('Betroffene Abrechnung').selectOption(fixture.statement_ids[0]);
    await dialog.getByLabel('Eingangsdatum').fill('2026-10-18');
    await dialog.getByLabel('Begründung des Widerspruchs').fill(reason);
    const creationRoute = `**/api/v1/billing/periods/${fixture.billing_period}/objections`;
    let lostAcknowledgement = false;
    await page.route(creationRoute, async route => {
      if (route.request().method() === 'POST' && !lostAcknowledgement) {
        lostAcknowledgement = true;
        const committed = await route.fetch();
        assert.ok(committed.ok(), 'The first creation committed before its response was lost');
        await route.abort('failed');
      } else await route.continue();
    });
    await dialog.getByRole('button', { name: 'Widerspruch speichern', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Widerspruch speichern', exact: true })).toBeEnabled();
    assert.ok(lostAcknowledgement);
    await dialog.getByRole('button', { name: 'Widerspruch speichern', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page.unroute(creationRoute);
    await expect(page.getByRole('button', { name: 'Widerspruch zurückweisen: ' + reason, exact: true })).toBeVisible();
    const rows = await call('GET', '/billing/objections?billing_period_id=' + fixture.billing_period);
    assert.equal(rows.length, 1); assert.equal(rows[0].statement_id, fixture.statement_ids[0]);
    assert.equal(rows[0].received_on, '2026-10-18');
  });
  await step('Objection: explicit rejection retains immutable PDFs and returns the known original status', async () => {
    await page.getByRole('button', { name: 'Widerspruch zurückweisen: ' + reason, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Widerspruch begründet zurückweisen', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Ablehnung mit Begründung bestätigen', exact: true })).toBeDisabled();
    await dialog.getByLabel('Sachliche Begründung (mindestens 12 Zeichen)').fill('QA Flächenunterlagen geprüft; Verteilung ist nachvollziehbar.');
    await page.setViewportSize({ width: 320, height: 900 });
    await fits();
    await page.screenshot({ path: path.join(output, 'objection-decision-320.png') });
    await dialog.getByRole('button', { name: 'Ablehnung mit Begründung bestätigen', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const rows = await call('GET', '/billing/objections?billing_period_id=' + fixture.billing_period);
    assert.equal(rows[0].status, 'rejected'); assert.equal(rows[0].decision_actor_id, user.id);
    assert.equal((await call('GET', '/billing/periods/' + fixture.billing_period)).status, 'finalized');
  });
  await step('Objection: a second reason opens one separate correction draft; every issued PDF stays byte-identical', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await call('POST', `/billing/periods/${fixture.billing_period}/objections`, {
      statement_id: fixture.statement_ids[1], received_on: '2026-10-18', reason: 'QA Nachgereichte Kosten prüfen' });
    await page.reload();
    await expect(page.getByRole('row').nth(1)).toContainText('Haus A');
    await page.getByRole('row').nth(1).click();
    await page.getByRole('button', { name: 'Abrechnung überarbeiten: QA Nachgereichte Kosten prüfen', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Abrechnung begründet überarbeiten', exact: true });
    await dialog.getByLabel('Sachliche Begründung (mindestens 12 Zeichen)').fill('QA Neue Kostenunterlagen erfordern eine getrennte Korrekturfassung.');
    await dialog.getByRole('button', { name: 'Überarbeitung mit Begründung starten', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const rows = await call('GET', '/billing/objections?billing_period_id=' + fixture.billing_period);
    const correction = rows.find(row => row.status === 'correction');
    assert.ok(correction?.correction_period_id);
    const draft = await call('GET', '/billing/periods/' + correction.correction_period_id);
    assert.equal(draft.status, 'draft'); assert.notEqual(draft.id, fixture.billing_period);
    assert.ok(rows.some(row => row.status === 'rejected'));
    for (const [index, id] of fixture.statement_ids.entries()) {
      const value = await api.get(`/api/v1/billing/statements/${id}/pdf`);
      assert.ok(value.ok()); assert.deepEqual(await value.body(), pdfs[index]);
    }
    await page.screenshot({ path: path.join(output, 'objection-correction-1440.png') });
    await page.setViewportSize({ width: 320, height: 900 });
    await fits();
    await page.screenshot({ path: path.join(output, 'objection-correction-320.png') });
  });
  assert.deepEqual(report.page_errors, []);
  assert.deepEqual(report.external, []);
} catch (e) {
  process.exitCode = 1;
  console.error(e);
} finally {
  await context?.close(); await api?.dispose(); await browser.close();
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
