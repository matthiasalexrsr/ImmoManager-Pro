import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function json(page, headers, path, data, method = data === undefined ? 'GET' : 'POST') {
  const response = await page.request.fetch('/api/v1' + path, { headers, method, data });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.locator('form input[type="text"]').fill(username);
  await page.locator('form input[type="password"]').fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  return { Authorization: 'Bearer ' + await page.evaluate(() => localStorage.getItem('access_token')) };
}

async function scenario(page) {
  const headers = await login(page), tag = randomUUID().slice(0, 8);
  expect((await (await page.request.get('/health')).json()).store_backend).toBe('SQLAlchemyStore');
  const portfolio = await json(page, headers, '/portfolios', { name: `Tax-${tag}` });
  const properties = [];
  for (const name of ['A', 'B']) properties.push(await json(page, headers, '/properties', { portfolio_id: portfolio.id, name: `Tax-${tag}-${name}`, property_type: 'MFH' }));
  const account = await json(page, headers, '/accounts', { portfolio_id: portfolio.id, name: `Cash-${tag}`, account_type: 'bank' });
  const categories = [];
  for (const [name, kind] of [['Rent', 'income'], ['Costs', 'expense']]) categories.push(await json(page, headers, '/categories', { portfolio_id: portfolio.id, name: `${name}-${tag}`, category_type: kind }));
  const cash = [];
  for (const [amount, category, property] of [[100.01, 0, 0], [-0.01, 0, 0], [-30.10, 1, null], [10.01, 1, 0]])
    cash.push(await json(page, headers, '/bookings', { account_id: account.id, category_id: categories[category].id, property_id: property === null ? null : properties[property].id,
      booking_date: '2024-06-01', amount, status: 'confirmed', payment_text: `Synthetic reviewed cash ${tag}` }));
  return { headers, tag, portfolio, properties, account, categories, cash };
}

async function open(page, fixture) {
  await page.goto('/annual-tax');
  await expect(page.getByRole('heading', { name: 'Steueraufbereitung', exact: true })).toBeVisible();
  await page.getByLabel('Steuerjahr', { exact: true }).fill('2024');
  await page.locator('.annual-tax-page').getByRole('combobox', { name: 'Portfolio', exact: true }).selectOption(fixture.portfolio.id);
  await expect(page.getByRole('button', { name: 'Zuordnung anlegen', exact: true })).toBeEnabled();
}

async function preflight(page) {
  const response = page.waitForResponse(row => row.url().endsWith('/reports/annual-tax/preflight') && row.request().method() === 'POST');
  await page.getByRole('button', { name: 'Vorprüfung starten', exact: true }).click();
  const result = await response; expect(result.status(), await result.text()).toBe(200);
  return result.json();
}

async function save(page) {
  await page.getByRole('button', { name: 'Geprüften Jahresstand sichern', exact: true }).click();
  const dialog = page.getByRole('alertdialog'); await expect(dialog).toBeVisible();
  const response = page.waitForResponse(row => row.url().endsWith('/reports/annual-tax/projections') && row.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Bestätigen', exact: true }).click();
  const result = await response; expect(result.status(), await result.text()).toBe(201);
  return result.json();
}

test('actual cash mapping, shared cent splits, persisted neutral evidence and a reviewed revision', async ({ page }, testInfo) => {
  test.setTimeout(100_000);
  const fixture = await scenario(page); await open(page, fixture);
  await page.getByRole('button', { name: 'Zuordnung anlegen', exact: true }).click();
  const form = page.getByRole('button', { name: 'Geprüfte Version speichern', exact: true }).locator('xpath=ancestor::form');
  await form.getByLabel('Bezeichnung', { exact: true }).fill(`Reviewed-${fixture.tag}`);
  await form.getByLabel('Geprüft durch', { exact: true }).fill('Synthetic adviser review');
  for (const [index, treatment, line] of [[0, 'income', 'Reviewed rental cash'], [1, 'expense', 'Reviewed costs']]) {
    if (index) await form.getByRole('button', { name: 'Kontenregel hinzufügen', exact: true }).click();
    const rule = form.getByRole('group', { name: `Kontenregel ${index + 1}`, exact: true });
    await rule.getByRole('combobox', { name: 'Geldkonto', exact: true }).selectOption(fixture.account.id);
    await rule.getByRole('combobox', { name: 'Buchungskategorie', exact: true }).selectOption(fixture.categories[index].id);
    await rule.getByRole('combobox', { name: 'Steuerliche Behandlung', exact: true }).selectOption(treatment);
    await rule.getByLabel('Selbst geprüfte Formularzeile', { exact: true }).fill(line);
    await rule.getByLabel('Begründung / Prüfnachweis', { exact: true }).fill('Actual source classification reviewed');
  }
  await form.locator('input[type="checkbox"]').check();
  await form.getByRole('button', { name: 'Geprüfte Version speichern', exact: true }).click();
  await expect(page.getByText('Die geprüfte Zuordnungsversion wurde gespeichert.', { exact: true })).toBeVisible();
  await page.getByLabel('Geldfluss-Stichtag', { exact: true }).fill('2024-12-31');
  const blocked = await preflight(page); expect(blocked.ready).toBe(false);
  expect(blocked.blocking_issue_counts.property_assignment_required).toBe(1);
  await expect(page.getByRole('button', { name: 'Geprüften Jahresstand sichern', exact: true })).toHaveCount(0);
  await page.getByText(/Quellenbeispiele ansehen/).click();
  const source = page.locator('.tax-source').filter({ hasText: fixture.cash[2].id });
  await source.getByRole('button', { name: 'Diesen Beleg zuordnen', exact: true }).click();
  const adjustment = page.getByRole('group', { name: 'Einzelzuordnung 1', exact: true });
  await adjustment.getByLabel('Grund der Einzelzuordnung', { exact: true }).fill('Actual reviewed shared costs preserve every cent');
  for (const [index, amount] of [[0, '-20.01'], [1, '-10.09']]) {
    if (index) await adjustment.getByRole('button', { name: 'Anteil hinzufügen', exact: true }).click();
    const part = adjustment.getByRole('group', { name: `Anteil ${index + 1}`, exact: true });
    await part.getByRole('combobox', { name: 'Objekt', exact: true }).selectOption(fixture.properties[index].id);
    await part.getByLabel('Signierter Geldfluss in EUR', { exact: true }).fill(amount);
    await part.getByRole('combobox', { name: 'Steuerliche Behandlung', exact: true }).selectOption('expense');
    await part.getByLabel('Selbst geprüfte Formularzeile', { exact: true }).fill('Reviewed costs');
    await part.getByLabel('Begründung / Prüfnachweis', { exact: true }).fill('Explicit property split from synthetic invoice');
  }
  const ready = await preflight(page);
  expect(ready).toMatchObject({ ready: true, confirmed_cash_rows: 4, totals: { cash_cents: '7991', income_cents: '10000', expense_cents: '2009' } });
  expect(ready.groups.find(row => row.property_id === fixture.properties[1].id && row.treatment === 'expense').amount_cents).toBe('1009');
  const saved = await save(page); expect(saved.revision_number).toBe(1);
  await page.reload();
  await page.getByLabel('Steuerjahr', { exact: true }).fill('2024'); await page.locator('.annual-tax-page').getByRole('combobox', { name: 'Portfolio', exact: true }).selectOption(fixture.portfolio.id);
  const record = page.locator('.tax-snapshot').filter({ hasText: saved.id }); await expect(record).toBeVisible();
  await record.getByRole('button', { name: 'Nachweise ansehen', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gesicherter Jahresstand', exact: true })).toBeVisible();
  const downloaded = page.waitForEvent('download'); await record.getByRole('button', { name: 'CSV-/JSON-Belege laden', exact: true }).click();
  const download = await downloaded, zip = await download.path();
  expect((await readFile(zip)).subarray(0, 2).toString()).toBe('PK');
  const inspected = spawnSync(process.env.IMMO_E2E_PYTHON || 'python', ['-c', 'import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({"manifest":json.loads(z.read("manifest.json")),"sources":[json.loads(r) for r in z.read("sources.jsonl").splitlines()]}))', zip], { encoding: 'utf8', windowsHide: true });
  expect(inspected.status, inspected.stderr).toBe(0);
  const evidence = JSON.parse(inspected.stdout); expect(evidence.sources.map(row => row.booking.id).sort()).toEqual(fixture.cash.map(row => row.id).sort());
  expect(evidence.sources.find(row => row.booking.id === fixture.cash[2].id).parts.map(part => part.amount_cents)).toEqual(['-2001', '-1009']);
  expect(evidence.manifest.compatibility).toBe('vendor_neutral_reviewed_cash_projection');
  await json(page, fixture.headers, '/bookings', { account_id: fixture.account.id, category_id: fixture.categories[0].id, property_id: fixture.properties[0].id,
    booking_date: '2024-07-01', amount: -1, status: 'confirmed', payment_text: 'Additional actual rent refund' });
  await record.getByRole('button', { name: 'Neue Jahresfassung vorbereiten', exact: true }).click();
  await expect(page.getByLabel('Grund der Einzelzuordnung', { exact: true })).toHaveValue('Actual reviewed shared costs preserve every cent');
  const revised = await preflight(page); expect(revised.totals.income_cents).toBe('9900');
  await page.getByLabel('Begründung der neuen Jahresfassung', { exact: true }).fill('Actual additional refund, original shared evidence retained');
  const second = await save(page); expect(second.revision_number).toBe(2); expect(second.previous_projection_id).toBe(saved.id);
  expect(second.revision_delta_cents.income_cents).toBe('-100');
  expect((await json(page, fixture.headers, `/reports/annual-tax/projections/${saved.id}`)).totals.income_cents).toBe('10000');
  await testInfo.attach('actual-tax-evidence.json', { body: JSON.stringify({ saved, second, source_ids: evidence.sources.map(row => row.booking.id) }, null, 2), contentType: 'application/json' });
  for (const [width, theme] of [[320, 'light'], [390, 'dark']]) {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(value => { document.documentElement.setAttribute('data-theme', value); document.body.setAttribute('data-theme', value); }, theme);
    // The shared shell animates its viewport transition; inspect the settled
    // layout, while still requiring the page itself to fit at both widths.
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    const layout = await page.evaluate(() => ({ width: window.innerWidth, document: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > window.innerWidth)
        .slice(0, 20).map(node => ({ tag: node.tagName, class: node.className, width: node.getBoundingClientRect().width, right: node.getBoundingClientRect().right })) }));
    expect(layout.document, JSON.stringify(layout)).toBeLessThanOrEqual(layout.width);
    await page.screenshot({ path: testInfo.outputPath(`tax-${width}-${theme}.png`), fullPage: true });
  }
});

for (const role of ['readonly', 'techniker']) test(`actual ${role} can read/download scoped tax evidence without finance commands and loses a revoked grant`, async ({ page }) => {
  const fixture = await scenario(page), path = '/reports/annual-tax';
  const version = await json(page, fixture.headers, path + '/profiles', { portfolio_id: fixture.portfolio.id, tax_year: 2024, currency: 'EUR', name: 'Synthetic reviewed classification', reviewed_by: 'Synthetic reviewer', review_confirmed: true,
    idempotency_key: randomUUID(), rules: fixture.categories.map((category, index) => ({ account_id: fixture.account.id, category_id: category.id, treatment: index ? 'expense' : 'income', form_line: 'User reviewed line', reason: 'Explicit synthetic classification' })) });
  const review = { profile_version_id: version.id, as_of: '2024-12-31', overrides: [{ booking_id: fixture.cash[2].id, reason: 'Explicit property proof', parts: [{ property_id: fixture.properties[0].id, amount_cents: '-3010', treatment: 'expense', form_line: 'User reviewed line', reason: 'Reviewed cost property' }] }] };
  const checked = await json(page, fixture.headers, path + '/preflight', review); expect(checked.ready).toBe(true);
  const saved = await json(page, fixture.headers, path + '/projections', { ...review, preview_hash: checked.preview_hash, idempotency_key: randomUUID() });
  const password = 'Synthetic tax passphrase 123', username = `tax-${role}-${fixture.tag}`;
  const user = await json(page, fixture.headers, '/auth/users', { username, password, email: `${username}@example.test`, full_name: 'Synthetic tax viewer', role, portfolio_access: 'selected', portfolio_ids: [fixture.portfolio.id] });
  await page.evaluate(() => { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); });
  const memberHeaders = await login(page, username, password);
  await page.goto('/annual-tax');
  await page.getByLabel('Steuerjahr', { exact: true }).fill('2024');
  await page.locator('.annual-tax-page').getByRole('combobox', { name: 'Portfolio', exact: true }).selectOption(fixture.portfolio.id);
  const row = page.locator('.tax-snapshot').filter({ hasText: saved.id }); await expect(row).toBeVisible();
  for (const name of ['Zuordnung anlegen', 'Vorprüfung starten', 'Neue Jahresfassung vorbereiten', 'Geprüften Jahresstand sichern']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  expect((await page.request.post('/api/v1' + path + '/preflight', { headers: memberHeaders, data: review })).status()).toBe(403);
  await row.getByRole('button', { name: 'Nachweise ansehen', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gesicherter Jahresstand', exact: true })).toBeVisible();
  const downloading = page.waitForEvent('download'); await row.getByRole('button', { name: 'CSV-/JSON-Belege laden', exact: true }).click();
  expect((await downloading).suggestedFilename()).toContain('annual-tax-2024');
  await json(page, fixture.headers, `/auth/users/${user.id}`, { portfolio_access: 'selected', portfolio_ids: [] }, 'PATCH');
  const denied = await page.request.get('/api/v1' + path + `/projections/${saved.id}/download`, { headers: memberHeaders });
  expect(denied.status()).toBe(404); expect(denied.headers()['content-disposition']).toBeUndefined();
  await page.getByRole('button', { name: 'Aktualisieren', exact: true }).click(); await expect(page.locator('.tax-snapshot')).toHaveCount(0);
  await expect(page.locator('.annual-tax-page').getByRole('alert')).toBeVisible();
});
