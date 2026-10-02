import { randomUUID } from 'node:crypto';
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

async function read(page, path, headers) {
  const response = await page.request.get(`/api/v1${path}`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function create(page, path, headers, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function fixture(page, headers) {
  const unique = randomUUID();
  const year = new Date().getUTCFullYear() + 2;
  const portfolio = await create(page, '/portfolios', headers, { name: `Lifecycle ${unique}` });
  const property = await create(page, '/properties', headers, {
    portfolio_id: portfolio.id, name: `Lifecycle property ${unique}`, property_type: 'residential',
  });
  const unit = await create(page, '/units', headers, {
    property_id: property.id, label: `Lifecycle ${unique}`, unit_type: 'apartment', cold_rent: 600,
  });
  const tenant = await create(page, '/tenants', headers, { full_name: `Synthetic lifecycle ${unique}` });
  const contract = await create(page, '/contracts', headers, {
    contract_number: `Lifecycle-parent-${unique}`, property_id: property.id, unit_id: unit.id,
    tenant_id: tenant.id, status: 'active', start_date: `${year}-01-01`, end_date: `${year}-12-31`,
    deposit_amount: 1500, notice_period: 'Synthetic manually reviewed notice', index_rent: 'index',
  });
  const charge = await create(page, '/rent-charges', headers, {
    contract_id: contract.id, month: `${year}-06`, cold_rent: 600,
  });
  const payment = await create(page, `/rent-charges/${charge.id}/payments`, headers, {
    idempotency_key: randomUUID(), amount: '100.00', payment_date: `${year}-06-01`,
  });
  const receivable = await create(page, '/receivables', headers, {
    contract_id: contract.id, description: 'Synthetic settlement due after rental end',
    due_date: `${year + 1}-02-01`, amount_due: 125,
  });
  const charged = await read(page, `/rent-charges/${charge.id}`, headers);
  return { unique, year, portfolio, contract, charge: charged, payment, receivable };
}

async function open(page, contract) {
  await page.goto('/contracts');
  await germanWorkspaceReady(page);
  await page.getByRole('searchbox', { name: 'Vertrag, Immobilie, Einheit oder Mieter suchen', exact: true }).fill(contract.contract_number);
  await page.getByRole('button', { name: 'Filter anwenden', exact: true }).click();
  const opener = page.getByRole('row').filter({ hasText: contract.contract_number })
    .getByRole('button', { name: 'Ablauf prüfen', exact: true });
  await expect(opener).toBeVisible();
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Verlängerung oder Kündigung', exact: true });
  await expect(dialog.getByRole('button', { name: 'Entwurf speichern', exact: true })).toBeVisible();
  return { dialog, opener };
}

async function review(page, dialog) {
  await dialog.getByRole('button', { name: 'Entwurf speichern', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Neu prüfen', exact: true })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Neu prüfen', exact: true }).click();
  await expect(dialog.getByRole('heading', { name: 'Prüfvorschau', exact: true })).toBeVisible();
}

async function confirm(page, dialog) {
  await dialog.getByRole('checkbox', { name: 'Ich habe die Prüfung, Daten und Warnungen bewusst geprüft.', exact: true }).check();
  await dialog.getByRole('button', { name: 'Bestätigung ausführen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
}

async function unchangedFinance(page, headers, box) {
  expect(await read(page, `/rent-charges/${box.charge.id}`, headers)).toEqual(box.charge);
  expect(await read(page, `/rent-charges/${box.charge.id}/payments`, headers)).toEqual([box.payment]);
  expect(await read(page, `/receivables/${box.receivable.id}`, headers)).toEqual(box.receivable);
}

test('a reviewed successor survives a real lost confirm response without copying finance', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const headers = await login(page);
  const box = await fixture(page, headers);
  const { dialog, opener } = await open(page, box.contract);
  const reason = `Explicit synthetic renewal ${box.unique}`;
  const successorNumber = `Lifecycle-successor-${box.unique}`;
  await dialog.getByLabel('Nachvollziehbarer Grund', { exact: true }).fill(reason);
  await dialog.getByLabel('Neue Vertragsnummer', { exact: true }).fill(successorNumber);
  await dialog.getByLabel('Beginn Folgevertrag', { exact: true }).fill(`${box.year + 1}-01-01`);
  await dialog.getByRole('checkbox', { name: 'Folgevertrag bewusst ohne Enddatum anlegen', exact: true }).check();
  await review(page, dialog);
  await expect(dialog).toContainText('1 Mietforderungen');
  await expect(dialog).toContainText('1 Forderungen nach Mietende');
  await expect(dialog).toContainText(box.receivable.description);

  const commands = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/confirm')) commands.push(request.postDataJSON());
  });
  let accepted;
  const confirmPattern = `**/api/v1/contracts/${box.contract.id}/lifecycle/drafts/*/confirm`;
  await page.route(confirmPattern, async route => {
    const response = await route.fetch();
    expect(response.status(), await response.text()).toBe(200);
    accepted = await response.json();
    await route.abort('failed');
  });
  await confirm(page, dialog);
  await expect(dialog.getByRole('button', { name: 'Exakten Befehl erneut senden', exact: true })).toBeVisible();
  expect(accepted.state).toBe('confirmed');
  const base = `/contracts/${box.contract.id}/lifecycle`;
  const beforeRetry = await read(page, `${base}/history`, headers);
  expect(beforeRetry.items).toHaveLength(1);
  await page.unroute(confirmPattern);
  await dialog.getByRole('button', { name: 'Exakten Befehl erneut senden', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Exakten Befehl erneut senden', exact: true })).toHaveCount(0);
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(await read(page, `${base}/history`, headers)).toEqual(beforeRetry);
  expect(await read(page, `/contracts/${box.contract.id}`, headers)).toEqual(box.contract);
  const successor = await read(page, `/contracts/${accepted.successor_contract_id}`, headers);
  expect(successor).toMatchObject({ contract_number: successorNumber, property_id: box.contract.property_id,
    unit_id: box.contract.unit_id, tenant_id: box.contract.tenant_id, start_date: `${box.year + 1}-01-01`,
    end_date: null, deposit_amount: null, notice_period: null, index_rent: null });
  await unchangedFinance(page, headers, box);
  await dialog.getByRole('button', { name: 'Bestätigter Verlauf', exact: true }).click();
  await dialog.getByRole('button').filter({ hasText: reason }).click();
  await expect(dialog).toContainText(accepted.successor_contract_id);
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect.poll(() => dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  }
  const screenshot = testInfo.outputPath('contract-lifecycle-mobile.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('contract-lifecycle-mobile', { path: screenshot, contentType: 'image/png' });
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).first().focus();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test('explicit supersession preserves the old reply and scoped readers see history without private drafts', async ({ page, browser }) => {
  test.setTimeout(150_000);
  const headers = await login(page);
  const box = await fixture(page, headers);
  const base = `/contracts/${box.contract.id}/lifecycle`;
  const { dialog } = await open(page, box.contract);
  async function termination(reason, end) {
    await dialog.getByRole('combobox', { name: 'Vorgang', exact: true }).selectOption('termination');
    await dialog.getByLabel('Nachvollziehbarer Grund', { exact: true }).fill(reason);
    await dialog.getByLabel('Bestätigtes Mietende (einschließlich)', { exact: true }).fill(end);
    await review(page, dialog);
  }
  const firstReason = `First synthetic termination ${box.unique}`;
  await termination(firstReason, `${box.year}-11-30`);
  await confirm(page, dialog);
  await expect.poll(async () => (await read(page, `${base}/history`, headers)).items.length).toBe(1);
  const originalHistory = (await read(page, `${base}/history`, headers)).items[0];
  expect(originalHistory.result.state).toBe('pending_effective');
  expect(await read(page, `/contracts/${box.contract.id}`, headers)).toMatchObject({ end_date: `${box.year}-11-30`, status: 'active' });

  await dialog.getByRole('button', { name: 'Entwurf & Prüfung', exact: true }).click();
  await dialog.getByRole('button', { name: 'Neuer Entwurf', exact: true }).click();
  const correctionReason = `Reviewed earlier correction ${box.unique}`;
  await termination(correctionReason, `${box.year}-10-31`);
  await expect(dialog).toContainText('Dieser Vorgang löst eine frühere Kündigung ab');
  await expect(dialog).toContainText(originalHistory.draft_id);
  await expect(dialog).toContainText(`${box.year}-11-30`);
  await confirm(page, dialog);
  await expect.poll(async () => (await read(page, `${base}/history`, headers)).items.length).toBe(2);
  const history = await read(page, `${base}/history`, headers);
  const first = history.items.find(item => item.id === originalHistory.id);
  const latest = history.items.find(item => item.id !== originalHistory.id);
  expect(first.result).toEqual(originalHistory.result);
  expect(first.current_state).toBe('superseded');
  expect(first.superseded_by_draft_id).toBe(latest.draft_id);
  expect(latest.supersedes_draft_id).toBe(first.draft_id);
  await unchangedFinance(page, headers, box);
  await dialog.getByRole('button', { name: 'Bestätigter Verlauf', exact: true }).click();
  await dialog.getByRole('button').filter({ hasText: firstReason }).click();
  await expect(dialog).toContainText('Dieser Vorgang wurde abgelöst');
  await expect(dialog.getByRole('button', { name: 'Kündigung manuell abschließen', exact: true })).toHaveCount(0);
  await dialog.getByRole('button').filter({ hasText: correctionReason }).click();
  const finalization = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/finalize'));
  await dialog.getByRole('button', { name: 'Kündigung manuell abschließen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  expect((await finalization).status()).toBe(409);
  expect((await read(page, `${base}/history`, headers)).items).toHaveLength(2);

  const parentResponse = await page.request.get(`/api/v1/contracts/${box.contract.id}`, { headers });
  expect(parentResponse.status()).toBe(200);
  const secret = `Unconfirmed private owner reason ${box.unique}`;
  const draft = await create(page, `${base}/drafts`, headers, { idempotency_key: randomUUID(),
    expected_contract_etag: parentResponse.headers().etag,
    data: { operation: 'termination', reason: secret, termination_end_date: `${box.year}-09-30` },
  });
  const username = `lifecycle-reader-${box.unique}`;
  const password = 'Synthetic Lifecycle Reader 2026';
  await create(page, '/auth/users', headers, { username, password, email: `${username}@example.com`,
    full_name: 'Synthetic scoped reader', role: 'readonly', portfolio_access: 'selected', portfolio_ids: [box.portfolio.id],
  });
  const readerContext = await browser.newContext();
  const reader = await readerContext.newPage();
  try {
    const readerHeaders = await login(reader, username, password);
    await reader.goto('/contracts');
    await reader.getByRole('row').filter({ hasText: box.contract.contract_number })
      .getByRole('button', { name: 'Ablauf prüfen', exact: true }).click();
    const readerDialog = reader.getByRole('dialog', { name: 'Verlängerung oder Kündigung', exact: true });
    await readerDialog.getByRole('button', { name: 'Eigene Entwürfe', exact: true }).click();
    await expect(readerDialog.getByText('Keine eigenen offenen Entwürfe.', { exact: true })).toBeVisible();
    await expect(readerDialog.getByRole('button', { name: 'Entwurf speichern', exact: true })).toHaveCount(0);
    expect((await read(reader, `${base}/drafts`, readerHeaders)).items).toEqual([]);
    expect((await reader.request.get(`/api/v1${base}/drafts/${draft.id}`, { headers: readerHeaders })).status()).toBe(404);
    await readerDialog.getByRole('button', { name: 'Bestätigter Verlauf', exact: true }).click();
    await readerDialog.getByRole('button').filter({ hasText: correctionReason }).click();
    await expect(readerDialog).toContainText(correctionReason);
    await expect(readerDialog).not.toContainText(secret);
    await expect(readerDialog.getByRole('button', { name: 'Kündigung manuell abschließen', exact: true })).toHaveCount(0);
    expect((await read(reader, `${base}/history`, readerHeaders)).items).toHaveLength(2);
  } finally { await readerContext.close(); }
});
