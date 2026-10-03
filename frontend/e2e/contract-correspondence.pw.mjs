import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

async function create(page, path, headers, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function read(page, path, headers) {
  const response = await page.request.get(`/api/v1${path}`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function fixture(page, headers) {
  const unique = randomUUID();
  const portfolio = await create(page, '/portfolios', headers, { name: `Correspondence ${unique}` });
  const property = await create(page, '/properties', headers, {
    portfolio_id: portfolio.id, name: `Correspondence property ${unique}`, property_type: 'residential',
  });
  const unit = await create(page, '/units', headers, { property_id: property.id, label: 'A', unit_type: 'apartment' });
  const tenant = await create(page, '/tenants', headers, { full_name: `Synthetic recipient ${unique}` });
  const contract = await create(page, '/contracts', headers, {
    contract_number: `Correspondence-${unique}`, property_id: property.id, unit_id: unit.id,
    tenant_id: tenant.id, status: 'active', start_date: '2026-01-01', end_date: '2030-12-31',
  });
  const data = { letter_date: '2026-10-02', deadline_date: '2026-11-05',
    deadline_basis: 'Synthetic management appointment explicitly checked', deadline_confirmed: true,
    recipient_name: tenant.full_name, recipient_address: 'Synthetic address 1\n12345 Example',
    subject: `Synthetic management appointment ${unique}`, body: `Explicit synthetic letter ${unique}` };
  return { unique, portfolio, contract, tenant, data, base: `/contracts/${contract.id}/correspondence` };
}

async function open(page, contract) {
  await page.goto('/contracts');
  await expect(page.getByRole('heading', { name: 'Verträge', level: 1, exact: true })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Vertrag, Immobilie, Einheit oder Mieter suchen', exact: true }).fill(contract.contract_number);
  await page.getByRole('button', { name: 'Filter anwenden', exact: true }).click();
  const opener = page.getByRole('row').filter({ hasText: contract.contract_number })
    .getByRole('button', { name: 'Ablauf prüfen', exact: true });
  await expect(opener).toBeVisible();
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Verlängerung oder Kündigung', exact: true });
  await dialog.getByRole('button', { name: 'Fristen & Schreiben', exact: true }).click();
  const area = dialog.getByRole('region', { name: 'Vertragskorrespondenz', exact: true });
  await expect(area.getByRole('button', { name: 'Freigegebene Schreiben', exact: true })).toBeEnabled();
  return { dialog, area, opener };
}

async function download(page, button) {
  const pending = page.waitForEvent('download');
  await button.click();
  const item = await pending;
  const bytes = await readFile(await item.path());
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');
  return bytes;
}

async function observed(page, area, box, headers, kind, dispatchId) {
  await area.getByRole('combobox', { name: 'Ereignis', exact: true }).selectOption(kind);
  if (dispatchId) await area.getByRole('combobox', { name: 'Zugehöriger Versandbeleg', exact: true }).selectOption(dispatchId);
  await area.getByLabel('Beobachtungsdatum', { exact: true }).fill(kind === 'received' ? '2026-10-04' : '2026-10-02');
  await area.getByRole('textbox', { name: 'Nachweisreferenz', exact: true }).fill(`Synthetic ${kind} reference`);
  await area.getByRole('textbox', { name: 'Nachweisnotiz', exact: true }).fill(`Explicit observed ${kind}, no automatic delivery`);
  await area.getByRole('checkbox', { name: 'Ich bestätige dieses tatsächlich beobachtete Ereignis und den zugehörigen Nachweis.', exact: true }).check();
  const accepted = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/events'));
  await area.getByRole('button', { name: 'Beobachtetes Ereignis erfassen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  const response = await accepted;
  expect(response.status(), await response.text()).toBe(201);
  const result = await response.json();
  await expect(area.getByRole('button', { name: 'Beobachtetes Ereignis erfassen', exact: true })).toBeDisabled();
  const events = await read(page, `${box.base}/drafts/${result.id}/events`, headers);
  expect(events.items.find(value => value.id === result.event.id).data.kind).toBe(kind);
  return result.event;
}

test('explicit letter approval survives a lost reply and preserves exact original, manual facts and calendar date', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const ownerHeaders = await login(page);
  const box = await fixture(page, ownerHeaders);
  const writer = `correspondence-writer-${box.unique}`;
  const password = 'Synthetic Correspondence Writer 2026';
  await create(page, '/auth/users', ownerHeaders, {
    username: writer, password, email: `${writer}@example.com`,
    full_name: 'Synthetic scoped writer', role: 'verwalter',
    portfolio_access: 'selected', portfolio_ids: [box.portfolio.id],
  });
  // The full suite deliberately leaves overdue claims in other portfolios.
  // Exercise the letter UI with the actual selected-portfolio actor scope.
  await page.evaluate(() => localStorage.clear());
  const headers = await login(page, writer, password);
  const { dialog, area, opener } = await open(page, box.contract);
  await area.getByRole('button', { name: 'Meine Schreibenentwürfe', exact: true }).click();
  await expect(area.getByLabel('Schreibendatum', { exact: true })).toBeEnabled();
  for (const [label, key] of Object.entries({ Schreibendatum: 'letter_date', Verwaltungsstichtag: 'deadline_date',
    'Grundlage des Verwaltungsstichtags': 'deadline_basis', Empfängername: 'recipient_name',
    Empfängeranschrift: 'recipient_address', Betreff: 'subject', Schreibentext: 'body' })) {
    await area.getByLabel(label, { exact: true }).fill(box.data[key]);
  }
  await area.getByRole('checkbox', { name: 'Ich habe diesen Verwaltungsstichtag und seine Grundlage selbst geprüft.', exact: true }).check();
  await dialog.getByRole('button', { name: 'Bestätigter Verlauf', exact: true }).click();
  await dialog.getByRole('button', { name: 'Fristen & Schreiben', exact: true }).click();
  await expect(area.getByRole('textbox', { name: 'Schreibentext', exact: true })).toHaveValue(box.data.body);
  await area.getByRole('button', { name: 'Schreibenentwurf speichern', exact: true }).click();
  await expect(area.getByRole('button', { name: 'Schreiben prüfen', exact: true })).toBeEnabled();
  const pendingReview = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/review'));
  await area.getByRole('button', { name: 'Schreiben prüfen', exact: true }).click();
  const reviewed = await (await pendingReview).json();
  const preview = await download(page, area.getByRole('button', { name: 'Geprüftes PDF herunterladen', exact: true }));
  expect(createHash('sha256').update(preview).digest('hex')).toBe(reviewed.review.pdf_sha256);
  const commands = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/approve')) commands.push(request.postDataJSON());
  });
  let approved;
  const pattern = `**/api/v1${box.base}/drafts/*/approve`;
  await page.route(pattern, async route => {
    const response = await route.fetch();
    expect(response.status(), await response.text()).toBe(200);
    approved = await response.json();
    await route.abort('failed');
  });
  await area.getByRole('checkbox', { name: 'Ich habe genau diese Fassung, den Empfänger und den Verwaltungsstichtag geprüft und gebe sie ausdrücklich frei.', exact: true }).check();
  await area.getByRole('button', { name: 'Schreiben verbindlich freigeben', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(area.getByRole('button', { name: 'Genauen Befehl erneut prüfen', exact: true })).toBeVisible();
  const beforeRetry = await read(page, `${box.base}/history`, headers);
  expect(beforeRetry.items).toHaveLength(1);
  await page.unroute(pattern);
  await area.getByRole('button', { name: 'Genauen Befehl erneut prüfen', exact: true }).click();
  await expect(area.getByRole('button', { name: 'Unverändertes freigegebenes PDF', exact: true })).toBeEnabled();
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(await read(page, `${box.base}/history`, headers)).toEqual(beforeRetry);
  expect(await download(page, area.getByRole('button', { name: 'Unverändertes freigegebenes PDF', exact: true }))).toEqual(preview);
  const dispatch = await observed(page, area, box, headers, 'dispatched');
  const receipt = await observed(page, area, box, headers, 'received', dispatch.id);
  expect(receipt.data.dispatch_event_id).toBe(dispatch.id);
  await area.getByRole('button', { name: 'Bestätigte Verwaltungsstichtage', exact: true }).click();
  await expect(area.getByRole('button').filter({ hasText: box.data.deadline_basis })).toContainText(box.data.deadline_date);
  await area.getByRole('button').filter({ hasText: box.data.deadline_basis }).click();
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect.poll(() => dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  }
  const screenshot = testInfo.outputPath('contract-correspondence-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('contract-correspondence-mobile', { path: screenshot, contentType: 'image/png' });
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).first().focus();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  const reopened = await open(page, box.contract);
  await reopened.area.getByRole('button').filter({ hasText: box.data.subject }).click();
  expect(await download(page, reopened.area.getByRole('button', { name: 'Unverändertes freigegebenes PDF', exact: true }))).toEqual(preview);
  expect(await read(page, `/contracts/${box.contract.id}`, headers)).toEqual(box.contract);
  const tickData = { as_of: box.data.deadline_date, days_ahead: 1, lookback_days: 1 };
  const scopedTick = await page.request.post('/api/v1/tasks/operational-tick', {
    headers, data: tickData,
  });
  expect(scopedTick.status()).toBe(403);
  // This is an installation-wide operation: use its operator and documented
  // default work budget, rather than a letter-specific arbitrary budget.
  const tick = await page.request.post('/api/v1/tasks/operational-tick', {
    headers: ownerHeaders, data: tickData,
  });
  expect(tick.status(), await tick.text()).toBe(200);
  const projected = await tick.json();
  expect(projected.correspondence.created).toBe(1);
  const calendar = await read(page, `/calendar/${projected.calendar_event_ids.at(-1)}`, headers);
  expect(calendar.event_date).toBe(box.data.deadline_date);
  expect(calendar.description).toContain(approved.review_hash);
});

test('scoped readers can read approved originals but never private drafts or foreign letters', async ({ page, browser }) => {
  test.setTimeout(150_000);
  const headers = await login(page);
  const box = await fixture(page, headers);
  const parent = await page.request.get(`/api/v1/contracts/${box.contract.id}`, { headers });
  const draft = await create(page, `${box.base}/drafts`, headers, {
    idempotency_key: randomUUID(), expected_contract_etag: parent.headers().etag, data: box.data,
  });
  const reviewResponse = await page.request.post(`/api/v1${box.base}/drafts/${draft.id}/review`, {
    headers, data: { idempotency_key: randomUUID(), expected_revision: draft.revision,
      expected_contract_etag: draft.source_contract_etag },
  });
  expect(reviewResponse.status(), await reviewResponse.text()).toBe(200);
  const reviewed = await reviewResponse.json();
  const approveResponse = await page.request.post(`/api/v1${box.base}/drafts/${draft.id}/approve`, {
    headers, data: { idempotency_key: randomUUID(), expected_revision: reviewed.revision,
      expected_contract_etag: reviewed.source_contract_etag, reviewed_hash: reviewed.review_hash, confirmed: true },
  });
  expect(approveResponse.status(), await approveResponse.text()).toBe(200);
  const original = await (await page.request.get(`/api/v1${box.base}/drafts/${draft.id}/download`, { headers })).body();
  const privateText = `Private working letter ${box.unique}`;
  const privateDraft = await create(page, `${box.base}/drafts`, headers, {
    idempotency_key: randomUUID(), expected_contract_etag: parent.headers().etag,
    data: { ...box.data, body: privateText, subject: privateText },
  });
  const password = 'Synthetic Correspondence Reader 2026';
  for (const [suffix, portfolios] of [['reader', [box.portfolio.id]], ['foreign', []]]) {
    const username = `correspondence-${suffix}-${box.unique}`;
    await create(page, '/auth/users', headers, { username, password, email: `${username}@example.com`,
      full_name: 'Synthetic scoped reader', role: 'readonly', portfolio_access: 'selected', portfolio_ids: portfolios });
    const context = await browser.newContext();
    const reader = await context.newPage();
    try {
      const readerHeaders = await login(reader, username, password);
      expect((await reader.request.get(`/api/v1${box.base}/drafts/${privateDraft.id}`, { headers: readerHeaders })).status()).toBe(404);
      if (suffix === 'foreign') {
        expect((await reader.request.get(`/api/v1${box.base}/history`, { headers: readerHeaders })).status()).toBe(404);
        expect((await reader.request.get(`/api/v1${box.base}/drafts/${draft.id}/download`, { headers: readerHeaders })).status()).toBe(404);
        await reader.goto('/contracts');
        await expect(reader.getByRole('row').filter({ hasText: box.contract.contract_number })).toHaveCount(0);
      } else {
        const opened = await open(reader, box.contract);
        await opened.area.getByRole('button').filter({ hasText: box.data.subject }).click();
        expect(await download(reader, opened.area.getByRole('button', { name: 'Unverändertes freigegebenes PDF', exact: true }))).toEqual(original);
        await opened.area.getByRole('button', { name: 'Meine Schreibenentwürfe', exact: true }).click();
        await expect(opened.area).not.toContainText(privateText);
        await expect(opened.area.getByRole('button', { name: 'Schreibenentwurf speichern', exact: true })).toHaveCount(0);
        await expect(opened.area.getByRole('button', { name: 'Beobachtetes Ereignis erfassen', exact: true })).toHaveCount(0);
        expect((await read(reader, `${box.base}/drafts`, readerHeaders)).items).toEqual([]);
      }
    } finally { await context.close(); }
  }
});
