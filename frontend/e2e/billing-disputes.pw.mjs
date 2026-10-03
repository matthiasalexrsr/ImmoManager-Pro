import { readFile } from 'node:fs/promises';
import { test, expect } from './demoFixtures.mjs';
import { appendNative, draftPath, finalize, financialIdentity, fixture, login, nativeApi, newOpen, openNative, openPeriod, responsive, sha256 } from './billingDisputeFixture.mjs';

const pathOf = response => new URL(response.url()).pathname;
const requestIs = (path, method) => response => pathOf(response) === `/api/v1${path}` && response.request().method() === method;
const caseDetail = page => page.locator('.dispute-case');
const commandForm = page => page.locator('.dispute-command');
async function attach(testInfo, name, value) { await testInfo.attach(name, { body: Buffer.from(JSON.stringify(value, null, 2)), contentType: 'application/json' }); }
async function inspect(page, receipt, statementId) {
  await page.getByRole('button', { name: `Akte · ${statementId}`, exact: true }).click();
  await expect(caseDetail(page).getByRole('region', { name: 'Chronik', exact: true })).toBeVisible();
  const currentRevision = caseDetail(page).locator(':scope > .dispute-facts > div').filter({ has: page.getByText('Revision', { exact: true }) }).locator('dd');
  await expect(currentRevision).toHaveText(String(receipt.revision));
}
async function uiEvent(page, caseId, action, reason) {
  await caseDetail(page).getByRole('button', { name: action, exact: true }).click(); const form = commandForm(page);
  await expect(form.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await form.getByLabel('Grund / Notiz', { exact: true }).fill(reason);
  await form.getByLabel('Tatsächliches Beobachtungsdatum', { exact: true }).fill('2026-10-02');
  await form.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  await expect(form.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toBeVisible();
  const saving = page.waitForResponse(requestIs(`/billing/disputes/${caseId}/events`, 'POST'));
  await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click();
  const saved = await saving; expect(saved.status(), await saved.text()).toBe(200);
  const receipt = await saved.json(); await expect(form).toHaveCount(0); return receipt;
}

test('C: real archived second-page original survives lost success and encrypted reload with the same command', async ({ page }, testInfo) => {
  test.setTimeout(240_000); const box = await fixture(page, 26); await openPeriod(page, box);
  const requests = []; page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/billing/disputes') requests.push(request.postDataJSON()); });
  const historyQueries = []; page.on('request', request => { if (request.method() === 'GET' && new URL(request.url()).pathname === `/api/v1/documents/${box.document.id}/versions`) historyQueries.push(new URL(request.url()).searchParams.toString()); });
  const form = await newOpen(page, box, true);
  await expect(form.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toContainText(box.original.filename);
  expect(historyQueries.some(query => new URLSearchParams(query).get('before') === '2')).toBeTruthy();
  await responsive(page, testInfo, 'C-reviewed-original');
  let committed;
  const routePath = '**/api/v1/billing/disputes';
  await page.route(routePath, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const actual = await route.fetch(); expect(actual.status(), await actual.text()).toBe(201);
    committed = await actual.json();
    // The native command really committed. Only delivery of its response fails.
    await route.abort('failed');
  });
  await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click();
  await expect(form.getByRole('button', { name: 'Denselben Befehl erneut senden', exact: true })).toBeVisible();
  expect(committed).toBeTruthy(); expect(requests).toHaveLength(1);
  const first = structuredClone(requests[0]);
  expect(first).toMatchObject({ evidence_version_ids: [box.original.id], line_item_refs: [0], expected_statement_revision: box.statement.revision, expected_snapshot_hash: box.statement.snapshot_hash });
  const before = await box.api(`/billing/disputes?period_id=${box.period.id}&page_size=25`);
  expect(before.items).toHaveLength(1); expect(before.items[0].id).toBe(committed.case_id);
  const original = await box.api(`/billing/disputes/${committed.case_id}/journal?after=0&page_size=25`);
  expect(original.items).toHaveLength(1); expect(original.items[0].evidence[0]).toMatchObject({ version_id: box.original.id, sha256: box.original.sha256, filename: box.original.filename });
  const retained = (await box.api(draftPath(box.actor.id, box.period.id))).draft;
  expect(retained.submission_pending).toBe(true); expect(JSON.parse(retained.values.command_json)).toEqual(first);
  await page.unroute(routePath); await page.reload();
  const periodRow = page.getByRole('row').filter({ has: page.getByRole('cell', { name: box.property.name, exact: true }) }); await periodRow.click();
  await expect(page.getByRole('heading', { name: box.period.label, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Neue Akte erfassen', exact: true }).click();
  await commandForm(page).getByRole('button', { name: 'Nach Bestandsprüfung weiterbearbeiten', exact: true }).click();
  await expect(commandForm(page).getByRole('button', { name: 'Denselben Befehl erneut senden', exact: true })).toBeVisible();
  await page.waitForTimeout(850);
  const restored = (await box.api(draftPath(box.actor.id, box.period.id))).draft;
  expect(restored.submission_pending).toBe(true); expect(restored.values.command_json).toBe(retained.values.command_json); expect(restored.values.review_json).toBe(retained.values.review_json);
  await expect(commandForm(page).getByLabel('Grund / Notiz', { exact: true })).toHaveCount(0);
  await expect(commandForm(page).getByRole('button', { name: 'Eingaben bearbeiten', exact: true })).toHaveCount(0);
  const replay = page.waitForResponse(requestIs('/billing/disputes', 'POST'));
  await commandForm(page).getByRole('button', { name: 'Denselben Befehl erneut senden', exact: true }).click();
  const response = await replay; expect(response.status(), await response.text()).toBe(201); expect(await response.json()).toEqual(committed);
  await expect(commandForm(page)).toHaveCount(0); expect(requests).toHaveLength(2); expect(requests[1]).toEqual(first);
  const proof = await box.api(`/billing/disputes/${committed.case_id}/journal?after=0&page_size=25`);
  expect(proof.items.map(row => row.id)).toEqual([committed.event_id]); expect(proof.revision).toBe(1);
  expect((await box.api(draftPath(box.actor.id, box.period.id))).draft).toBeNull();
  expect(financialIdentity(await box.api(`/billing/statements/${box.statement.id}`))).toEqual(financialIdentity(box.statement));
  await attach(testInfo, 'C-real-lost-success-replay', { originalRequest: first, replayRequest: requests[1], receipt: committed, evidence: proof.items[0].evidence, pendingAfter850ms: restored.submission_pending });
});

test('C: actual concurrent journal 409 retains input until explicit current revision adoption', async ({ page }, testInfo) => {
  test.setTimeout(180_000); const box = await fixture(page); const initial = await openNative(box); await openPeriod(page, box); await inspect(page, initial, box.statement.id);
  await caseDetail(page).getByRole('button', { name: 'Notiz hinzufügen', exact: true }).click(); const form = commandForm(page);
  await expect(form.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  const reason = `Erhaltener eigener Grund ${box.tag}`; await form.getByLabel('Grund / Notiz', { exact: true }).fill(reason);
  await form.getByLabel('Tatsächliches Beobachtungsdatum', { exact: true }).fill('2026-10-02');
  const previewResponse = page.waitForResponse(requestIs(`/billing/disputes/${initial.case_id}/preview`, 'POST'));
  await form.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click(); const reviewed = await (await previewResponse).json();
  expect(reviewed.request.expected_revision).toBe(1);
  const other = await appendNative(box, initial.case_id, 'note', 'Actually confirmed independent note'); expect(other.revision).toBe(2);
  const rejected = page.waitForResponse(requestIs(`/billing/disputes/${initial.case_id}/events`, 'POST'));
  await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click(); const failed = await rejected;
  expect(failed.status(), await failed.text()).toBe(409); expect(failed.request().postDataJSON()).toMatchObject({ idempotency_key: reviewed.request.idempotency_key, expected_revision: 1, reason });
  await expect(form.getByLabel('Grund / Notiz', { exact: true })).toHaveValue(reason);
  await expect(form.getByLabel('Tatsächliches Beobachtungsdatum', { exact: true })).toHaveValue('2026-10-02');
  await expect(form.getByRole('button', { name: 'Vorschau prüfen', exact: true })).toBeDisabled();
  const adopt = form.getByRole('button', { name: 'Geprüften Originalstand übernehmen', exact: true }); await expect(adopt).toBeVisible();
  await adopt.focus(); await page.keyboard.press('Enter');
  await form.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  await expect(form.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toBeVisible();
  const confirmed = page.waitForResponse(requestIs(`/billing/disputes/${initial.case_id}/events`, 'POST'));
  await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click(); const saved = await confirmed;
  expect(saved.status(), await saved.text()).toBe(200); const request = saved.request().postDataJSON();
  expect(request).toMatchObject({ idempotency_key: reviewed.request.idempotency_key, expected_revision: 2, reason });
  const receipt = await saved.json(); expect(receipt.revision).toBe(3); await expect(form).toHaveCount(0);
  const journal = await box.api(`/billing/disputes/${initial.case_id}/journal?after=0&page_size=25`);
  expect(journal.items.map(row => row.reason)).toEqual([`Native original ${box.tag}`, 'Actually confirmed independent note', reason]);
  await attach(testInfo, 'C-native409-preserved-command', { rejected: failed.request().postDataJSON(), confirmed: request, receipt });
});

test('C: real server grant 403 and portfolio 404 hide preserved originals without a domain write', async ({ page, browser }, testInfo) => {
  test.setTimeout(180_000); const box = await fixture(page); const password = 'SyntheticJournal42!'; const username = `c-member-${box.tag}`;
  const actor = await box.api('/auth/users', { username, password, email: `${username}@example.test`, full_name: 'Synthetic C Scoped Manager', role: 'verwalter', portfolio_access: 'selected', portfolio_ids: [box.portfolio.id] }, 'POST', 201);
  const context = await browser.newContext({ baseURL: process.env.IMMO_E2E_URL, locale: 'de-DE', timezoneId: 'Europe/Berlin', viewport: { width: 1440, height: 1000 } });
  const member = await context.newPage(); const errors = []; member.on('pageerror', error => errors.push(error.message));
  try {
    const headers = await login(member, username, password); const memberApi = nativeApi(member, headers); const token = await member.evaluate(() => localStorage.getItem('access_token'));
    await openPeriod(member, box); const form = await newOpen(member, box, true);
    await expect.poll(async () => Boolean((await memberApi(draftPath(actor.id, box.period.id))).draft?.values.review_json)).toBe(true);
    await box.api(`/auth/users/${actor.id}`, { role: 'readonly' }, 'PATCH', 200);
    const denied = member.waitForResponse(requestIs('/auth/users/me/form-drafts', 'PUT'));
    await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click(); const forbidden = await denied;
    expect(forbidden.status(), await forbidden.text()).toBe(403);
    await expect(member.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toHaveCount(0);
    await expect(commandForm(member)).toHaveCount(0);
    await expect(member.locator('.billing-disputes')).toContainText('Der Zugriff wurde geändert oder die Akte ist nicht verfügbar.');
    expect((await box.api(`/billing/disputes?period_id=${box.period.id}&page_size=25`)).items).toHaveLength(0);
    expect(await member.evaluate(() => localStorage.getItem('access_token'))).toBe(token);
    await box.api(`/auth/users/${actor.id}`, { role: 'verwalter' }, 'PATCH', 200);
    await openPeriod(member, box); await member.getByRole('button', { name: 'Neue Akte erfassen', exact: true }).click();
    await commandForm(member).getByRole('button', { name: 'Entwurf wiederherstellen', exact: true }).click();
    await expect(commandForm(member).getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toBeVisible();
    // Same live JWT, removed source portfolio. Existing original bytes must not
    // escape through a download that was prepared under the previous scope.
    await box.api(`/auth/users/${actor.id}`, { portfolio_access: 'selected', portfolio_ids: [] }, 'PATCH', 200);
    const hidden = member.waitForResponse(requestIs(`/documents/${box.document.id}/versions/${box.original.id}/download`, 'GET'));
    await commandForm(member).getByRole('button', { name: 'Original herunterladen', exact: true }).click(); const missing = await hidden;
    expect(missing.status(), await missing.text()).toBe(404); await expect(commandForm(member)).toHaveCount(0);
    expect((await box.api(`/billing/disputes?period_id=${box.period.id}&page_size=25`)).items).toHaveLength(0);
    const proof = await member.request.get(`/api/v1/billing/disputes/periods/${box.period.id}/status`, { headers }); expect(proof.status()).toBe(404);
    expect(errors).toEqual([]); await responsive(member, testInfo, 'C-native-scope-hide');
    await attach(testInfo, 'C-native-scope-statuses', { draftWrite: forbidden.status(), archivedDownload: missing.status(), protectedPeriod: proof.status(), caseCount: 0 });
  } finally { await context.close(); }
});

test('C: native state actions, original-event correction, actual lineage and original bytes remain append-only', async ({ page }, testInfo) => {
  test.setTimeout(240_000); const box = await fixture(page); const initial = await openNative(box); await openPeriod(page, box); await inspect(page, initial, box.statement.id);
  const actions = [['Notiz hinzufügen', 'note', 'open'], ['Prüfung erfassen', 'in_review', 'in_review'], ['Rücknahme erfassen', 'withdrawn', 'withdrawn'],
    ['Akte wiederaufnehmen', 'reopened', 'open'], ['Akte abschließen', 'closed', 'closed'], ['Akte wiederaufnehmen', 'reopened', 'open']];
  for (const [label, kind, state] of actions) {
    const result = await uiEvent(page, initial.case_id, label, `Tatsächliche Aktion ${kind}`);
    const actual = await box.api(`/billing/disputes/${initial.case_id}`); expect(actual).toMatchObject({ revision: result.revision, state }); expect(actual.latest_event.kind).toBe(kind);
  }
  await box.api(`/tenants/${box.tenants[0].id}`, { full_name: `Aktuelle Namensänderung ${box.tag}` }, 'PATCH', 200);
  await caseDetail(page).getByRole('button', { name: 'Originalereignis öffnen · Revision 1', exact: true }).click();
  const event = caseDetail(page).getByRole('region', { name: 'Originalereignis', exact: true }); await expect(event).toContainText(`Native original ${box.tag}`);
  const correction = await uiEvent(page, initial.case_id, 'Originalereignis berichtigen', 'Eigenständige tatsächliche Berichtigung');
  const correctedEvent = await box.api(`/billing/disputes/${initial.case_id}/events/${correction.event_id}`); expect(correctedEvent.corrects_event_id).toBe(initial.event_id);
  const original = await box.api(`/billing/disputes/${initial.case_id}/events/${initial.event_id}`); expect(original.reason).toBe(`Native original ${box.tag}`); expect(original.observed_on).toBe('2026-10-01');
  expect(financialIdentity(await box.api(`/billing/statements/${box.statement.id}`))).toEqual(financialIdentity(box.statement));
  const revised = await box.api(`/billing/periods/${box.period.id}/revisions?revision_notes=Actual%20C%20correction`, {}, 'POST', 200);
  const correctionPeriod = await finalize(box.api, revised.new_period_id);
  const choices = await box.api(`/workflow-references/statements?dispute_case_id=${initial.case_id}&page_size=25`); expect(choices.items).toHaveLength(1);
  const choice = choices.items[0]; expect(choice.billing_period_id).toBe(correctionPeriod.period.id); expect(choice.billing_period_id).not.toBe(box.period.id);
  const source = await box.api(`/billing/statements/${box.statement.id}`);
  await caseDetail(page).getByRole('button', { name: 'Korrekturabrechnung verknüpfen', exact: true }).click(); const form = commandForm(page);
  await expect(form.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await form.getByLabel('Grund / Notiz', { exact: true }).fill('Tatsächlich finalisierte Quellenkorrektur'); await form.getByLabel('Tatsächliches Beobachtungsdatum', { exact: true }).fill('2026-10-02');
  await form.getByRole('button', { name: choice.label, exact: true }).click(); await form.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  await expect(form.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toBeVisible();
  const linked = page.waitForResponse(requestIs(`/billing/disputes/${initial.case_id}/events`, 'POST'));
  await form.getByRole('button', { name: 'Unverändert bestätigen', exact: true }).click(); const reply = await linked; expect(reply.status(), await reply.text()).toBe(200); const linkedReceipt = await reply.json(); await expect(form).toHaveCount(0);
  const link = await box.api(`/billing/disputes/${initial.case_id}/events/${linkedReceipt.event_id}`); expect(link).toMatchObject({ kind: 'correction_link', correction_statement_id: choice.id, correction_snapshot_hash: choice.snapshot_hash });
  const frozen = await box.api(`/billing/disputes/${initial.case_id}`); expect(frozen.original_snapshot.original_party.identity.full_name).toBe(box.tenants[0].full_name);
  expect(financialIdentity(await box.api(`/billing/statements/${box.statement.id}`))).toEqual(financialIdentity(source));
  // Cross the real chronology page boundary with actual independent events.
  for (let revision = frozen.revision; revision < 27; revision += 1) await appendNative(box, initial.case_id, 'note', `Native bounded chronology ${revision + 1}`);
  await page.getByRole('button', { name: 'Aktuellen Stand laden', exact: true }).first().click();
  const history = caseDetail(page).getByRole('region', { name: 'Chronik', exact: true });
  await expect(history.locator(':scope > ol > li')).toHaveCount(25);
  await history.getByRole('navigation', { name: 'Chronik', exact: true }).getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(history.locator(':scope > ol > li')).toHaveCount(2);
  await history.getByRole('navigation', { name: 'Chronik', exact: true }).getByRole('button', { name: 'Vorherige Seite', exact: true }).click();
  await expect(history.locator(':scope > ol > li')).toHaveCount(25);
  const downloading = page.waitForEvent('download');
  await history.locator('.dispute-evidence').first().getByRole('button', { name: 'Original herunterladen', exact: true }).click();
  const download = await downloading; expect(download.suggestedFilename()).toBe(box.original.filename); expect(await download.failure()).toBeNull();
  const path = testInfo.outputPath('C-actual-original.txt'); await download.saveAs(path); const bytes = await readFile(path); expect(bytes.equals(box.originalBytes)).toBe(true); expect(sha256(bytes)).toBe(box.original.sha256); expect(bytes.length).toBe(box.original.size_bytes);
  await responsive(page, testInfo, 'C-native-case-original'); await testInfo.attach('C-actual-original', { path, contentType: 'text/plain' });
  await attach(testInfo, 'C-native-correction-lineage', { correctedEvent: correctedEvent.id, correctsOriginal: correctedEvent.corrects_event_id, linkedEvent: link.id, correctionStatement: choice,
    originalPerson: frozen.original_snapshot.original_party.identity.full_name, chronologyRevision: (await box.api(`/billing/disputes/${initial.case_id}`)).revision });
});
