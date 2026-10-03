import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const READER_PASSWORD = 'Synthetic Financial Browser Passphrase 2026!';

async function apiLogin(page, username, password) {
  const response = await page.request.post('/api/v1/auth/login', { data: { username, password } });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).access_token;
}

async function uiLogin(page, username, password) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

async function create(page, headers, path, data) {
  const response = await page.request.post('/api/v1' + path, { headers, data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

function centsToApiNumber(cents) {
  return Number(cents) / 100;
}

function moneyDe(cents) {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const whole = (absolute / 100n).toString();
  const fraction = (absolute % 100n).toString().padStart(2, '0');
  const groups = [];
  for (let end = whole.length; end > 0; end -= 3) {
    groups.unshift(whole.slice(Math.max(0, end - 3), end));
  }
  return `${negative ? '-' : ''}${groups.join('.')},${fraction} €`;
}

function dateFor(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

async function seedFinancialFixture(page) {
  const ownerToken = await apiLogin(page, 'demo', 'Demo1234');
  const owner = { Authorization: `Bearer ${ownerToken}` };
  const suffix = randomUUID().slice(0, 8);
  const visiblePortfolio = await create(page, owner, '/portfolios', { name: `Browser Cash A ${suffix}` });
  const hiddenPortfolio = await create(page, owner, '/portfolios', { name: `Browser Cash Hidden ${suffix}` });
  const propertyA = await create(page, owner, '/properties', {
    portfolio_id: visiblePortfolio.id,
    name: `Cash Haus A ${suffix}`,
    property_type: 'residential',
    city: 'Berlin',
  });
  const propertyB = await create(page, owner, '/properties', {
    portfolio_id: visiblePortfolio.id,
    name: `Cash Haus B ${suffix}`,
    property_type: 'residential',
    city: 'Berlin',
  });
  const hiddenProperty = await create(page, owner, '/properties', {
    portfolio_id: hiddenPortfolio.id,
    name: `Cash Hidden Haus ${suffix}`,
    property_type: 'residential',
    city: 'Berlin',
  });
  const unitA = await create(page, owner, '/units', {
    property_id: propertyA.id,
    label: `Cash Wohnung A ${suffix}`,
    unit_type: 'apartment',
  });
  const account = await create(page, owner, '/accounts', {
    portfolio_id: visiblePortfolio.id,
    name: `Cash Konto A ${suffix}`,
    account_type: 'Girokonto',
  });
  const hiddenAccount = await create(page, owner, '/accounts', {
    portfolio_id: hiddenPortfolio.id,
    name: `Cash Hidden Konto ${suffix}`,
    account_type: 'Girokonto',
  });
  const categoryCent = await create(page, owner, '/categories', {
    portfolio_id: visiblePortfolio.id,
    name: `Centgenau ${suffix}`,
    category_type: 'income',
  });
  const categoryRent = await create(page, owner, '/categories', {
    portfolio_id: visiblePortfolio.id,
    name: `Miete ${suffix}`,
    category_type: 'income',
  });
  const categoryExpense = await create(page, owner, '/categories', {
    portfolio_id: visiblePortfolio.id,
    name: `Betrieb ${suffix}`,
    category_type: 'expense',
  });
  const visible = [];
  const addBooking = async ({
    cents, date, category, property, unit = null, status = 'confirmed', label, receipt = null,
  }) => {
    const row = await create(page, owner, '/bookings', {
      account_id: account.id,
      category_id: category.id,
      property_id: property.id,
      unit_id: unit?.id || null,
      booking_date: date,
      amount: centsToApiNumber(cents),
      status,
      payment_text: label,
      receipt_url: receipt,
    });
    visible.push({ ...row, cents, label });
    return row;
  };

  await addBooking({
    cents: 10n, date: '2026-01-01', category: categoryCent, property: propertyA, unit: unitA,
    label: `FW ${suffix} cent 0.10`,
  });
  await addBooking({
    cents: 20n, date: '2026-01-02', category: categoryCent, property: propertyA, unit: unitA,
    label: `FW ${suffix} cent 0.20`,
  });
  for (let day = 3; day <= 30; day += 1) {
    await addBooking({
      cents: 100n, date: dateFor(2026, 1, day), category: categoryRent, property: propertyA, unit: unitA,
      label: `FW ${suffix} rent jan ${String(day).padStart(2, '0')}`,
    });
  }
  for (let day = 1; day <= 25; day += 1) {
    await addBooking({
      cents: -200n, date: dateFor(2026, 2, day), category: categoryExpense, property: propertyB,
      label: `FW ${suffix} expense feb ${String(day).padStart(2, '0')}`,
    });
  }
  const formula = await addBooking({
    cents: 170n,
    date: '2026-02-15',
    category: categoryRent,
    property: propertyA,
    unit: unitA,
    label: `=SUM(2,3) FW ${suffix} protected csv`,
    receipt: `/synthetic-financial-receipts/${suffix}/receipt-1.pdf`,
  });
  const unconfirmed = await addBooking({
    cents: 500n, date: '2026-02-26', category: categoryRent, property: propertyA, unit: unitA,
    status: 'open', label: `FW ${suffix} unconfirmed`,
  });
  const cancelled = await addBooking({
    cents: 700n, date: '2026-02-27', category: categoryRent, property: propertyA, unit: unitA,
    status: 'cancelled', label: `FW ${suffix} cancelled`,
  });
  const afterCutoffA = await addBooking({
    cents: 300n, date: '2026-03-01', category: categoryRent, property: propertyA, unit: unitA,
    label: `FW ${suffix} after cutoff A`,
  });
  const afterCutoffB = await addBooking({
    cents: 400n, date: '2026-03-02', category: categoryRent, property: propertyB,
    label: `FW ${suffix} after cutoff B`,
  });
  const hiddenBooking = await create(page, owner, '/bookings', {
    account_id: hiddenAccount.id,
    property_id: hiddenProperty.id,
    booking_date: '2026-01-10',
    amount: 999.99,
    status: 'confirmed',
    payment_text: `FW ${suffix} HIDDEN`,
  });

  const username = `financial-browser-${suffix}`;
  const reader = await create(page, owner, '/auth/users', {
    username,
    email: `${username}@example.test`,
    full_name: `Synthetic Financial Browser ${suffix}`,
    password: READER_PASSWORD,
    role: 'verwalter',
    portfolio_access: 'selected',
    portfolio_ids: [visiblePortfolio.id],
  });
  const readerToken = await apiLogin(page, username, READER_PASSWORD);
  const readerHeaders = { Authorization: `Bearer ${readerToken}` };
  const preferences = await page.request.put('/api/v1/auth/users/me/preferences', {
    headers: readerHeaders,
    data: { locale: 'de-DE', theme: 'light', sidebar_collapsed: false },
  });
  expect(preferences.status(), await preferences.text()).toBe(200);

  return {
    suffix, owner, reader, username, readerHeaders,
    visiblePortfolio, hiddenPortfolio,
    propertyA, propertyB, hiddenProperty, unitA,
    account, hiddenAccount,
    categoryCent, categoryRent, categoryExpense,
    visible, hiddenBooking, formula, unconfirmed, cancelled, afterCutoffA, afterCutoffB,
  };
}

async function chooseReference(page, label, searchText, optionText) {
  const input = page.getByLabel(`${label} suchen`, { exact: true });
  await input.fill(searchText);
  await page.getByRole('button', { name: optionText, exact: true }).click();
}

async function tabTo(page, locator, maxTabs = 6) {
  for (let count = 0; count <= maxTabs; count += 1) {
    if (await locator.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  await expect(locator).toBeFocused();
}

function reportRequests(page, target) {
  page.on('request', request => {
    const url = new URL(request.url());
    if (request.method() === 'GET' && url.pathname.startsWith('/api/v1/reports/cash')) target.push(url);
  });
}

function sourceTable(page) {
  return page.locator('.financial-workspace__sources table');
}

test('FinancialWorkspace: real scoped cash report, exact sums, source pages, hash conflict, complete CSV and responsive keyboard flow', async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const fixture = await seedFinancialFixture(page);
  await uiLogin(page, fixture.username, READER_PASSWORD);

  const reportCalls = [];
  const referenceCalls = [];
  reportRequests(page, reportCalls);
  page.on('request', request => {
    const url = new URL(request.url());
    if (request.method() === 'GET' && url.pathname.startsWith('/api/v1/workflow-references/')) {
      referenceCalls.push(url);
    }
  });

  await page.goto('/financial-workspace');
  await expect(page.getByRole('heading', { name: 'Finanzauswertungen', exact: true })).toBeVisible();
  await expect(page.getByText('Diese Sicht zeigt Zahlungsflüsse.', { exact: false })).toBeVisible();

  const portfolioSearch = page.getByLabel('Portfolio suchen', { exact: true });
  const hiddenPortfolioLookup = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/workflow-references/portfolios'
      && url.searchParams.get('search') === fixture.hiddenPortfolio.name
      && response.status() === 200;
  });
  await portfolioSearch.fill(fixture.hiddenPortfolio.name);
  const hiddenPortfolioPage = await (await hiddenPortfolioLookup).json();
  expect(hiddenPortfolioPage.items.some(item => item.id === fixture.hiddenPortfolio.id)).toBe(false);
  await expect(page.getByRole('button', { name: fixture.hiddenPortfolio.name, exact: true })).toHaveCount(0);
  await chooseReference(page, 'Portfolio', fixture.visiblePortfolio.name, fixture.visiblePortfolio.name);

  const accountSearch = page.getByLabel('Konto suchen', { exact: true });
  const hiddenAccountLookup = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/workflow-references/accounts'
      && url.searchParams.get('search') === fixture.hiddenAccount.name
      && url.searchParams.get('portfolio_id') === fixture.visiblePortfolio.id
      && response.status() === 200;
  });
  await accountSearch.fill(fixture.hiddenAccount.name);
  const hiddenAccountPage = await (await hiddenAccountLookup).json();
  expect(hiddenAccountPage.items.some(item => item.id === fixture.hiddenAccount.id)).toBe(false);
  await expect(page.getByRole('button', { name: fixture.hiddenAccount.name, exact: true })).toHaveCount(0);
  await chooseReference(page, 'Konto', fixture.account.name, fixture.account.name);

  const hiddenCash = await page.request.get(
    `/api/v1/reports/cash?portfolio_id=${encodeURIComponent(fixture.hiddenPortfolio.id)}&basis=confirmed_cash&as_of=2026-02-28`,
    { headers: fixture.readerHeaders },
  );
  expect([403, 404]).toContain(hiddenCash.status());
  const hiddenCashBody = await hiddenCash.text();
  expect(hiddenCashBody).not.toContain(fixture.hiddenPortfolio.name);
  expect(hiddenCashBody).not.toContain(fixture.hiddenBooking.id);

  await chooseReference(page, 'Immobilie hinzufügen', fixture.propertyA.name, fixture.propertyA.name);
  await chooseReference(page, 'Einheit', fixture.unitA.label, fixture.unitA.label);

  await expect.poll(() => referenceCalls.some(url =>
    url.pathname.endsWith('/workflow-references/accounts')
      && url.searchParams.get('portfolio_id') === fixture.visiblePortfolio.id
      && !url.searchParams.has('property_id'))).toBeTruthy();
  await expect.poll(() => referenceCalls.some(url =>
    url.pathname.endsWith('/workflow-references/properties')
      && url.searchParams.get('portfolio_id') === fixture.visiblePortfolio.id)).toBeTruthy();
  await expect.poll(() => referenceCalls.some(url =>
    url.pathname.endsWith('/workflow-references/units')
      && url.searchParams.get('portfolio_id') === fixture.visiblePortfolio.id
      && url.searchParams.get('property_id') === fixture.propertyA.id)).toBeTruthy();

  const dateFrom = page.getByLabel('Zeitraum von', { exact: true });
  const dateTo = page.getByLabel('Zeitraum bis', { exact: true });
  const asOf = page.getByLabel('Stichtag', { exact: true });
  await dateFrom.fill('2026-03-31');
  await dateTo.fill('2026-01-01');
  await asOf.fill('2026-02-28');
  await dateFrom.focus();
  await expect(dateFrom).toBeFocused();
  await tabTo(page, dateTo);

  const reportsBeforeInvalid = reportCalls.filter(url => url.pathname === '/api/v1/reports/cash').length;
  const apply = page.getByRole('button', { name: 'Auswertung anwenden', exact: true });
  await apply.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Die Filter passen nicht zusammen');
  expect(reportCalls.filter(url => url.pathname === '/api/v1/reports/cash')).toHaveLength(reportsBeforeInvalid);

  await dateFrom.fill('2026-01-01');
  await dateTo.fill('2026-03-31');
  const singleReportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/reports/cash' && response.status() === 200);
  await apply.focus();
  await page.keyboard.press('Enter');
  const singleResponse = await singleReportResponse;
  const singleUrl = new URL(singleResponse.url());
  expect(singleUrl.searchParams.get('date_from')).toBe('2026-01-01');
  expect(singleUrl.searchParams.get('date_to')).toBe('2026-03-31');
  expect(singleUrl.searchParams.get('portfolio_id')).toBe(fixture.visiblePortfolio.id);
  expect(singleUrl.searchParams.getAll('property_ids')).toEqual([fixture.propertyA.id]);
  expect(singleUrl.searchParams.get('unit_id')).toBe(fixture.unitA.id);
  expect(singleUrl.searchParams.get('account_id')).toBe(fixture.account.id);
  expect(singleUrl.searchParams.get('basis')).toBe('confirmed_cash');
  expect(singleUrl.searchParams.get('as_of')).toBe('2026-02-28');
  await expect(page.locator('.financial-workspace__metrics')).toContainText('30,00 €');

  const unitGroup = page.getByRole('group', { name: 'Einheit' });
  await unitGroup.getByRole('button', { name: 'Auswahl entfernen', exact: true }).click();
  await chooseReference(page, 'Immobilie hinzufügen', fixture.propertyB.name, fixture.propertyB.name);

  const multiReportResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/reports/cash' && response.status() === 200);
  const firstSourcesResponse = page.waitForResponse(response => {
    const url = new URL(response.url());
    const properties = url.searchParams.getAll('property_ids').sort();
    return url.pathname === '/api/v1/reports/cash/sources'
      && !url.searchParams.has('after')
      && !url.searchParams.has('unit_id')
      && properties.length === 2
      && properties[0] === [fixture.propertyA.id, fixture.propertyB.id].sort()[0]
      && properties[1] === [fixture.propertyA.id, fixture.propertyB.id].sort()[1]
      && response.status() === 200;
  });
  await apply.click();
  const multiResponse = await multiReportResponse;
  const multiJson = await multiResponse.json();
  const firstSourcesHttp = await firstSourcesResponse;
  const firstSourcesUrl = new URL(firstSourcesHttp.url());
  const firstSources = await firstSourcesHttp.json();
  const multiUrl = new URL(multiResponse.url());
  expect(multiUrl.searchParams.getAll('property_ids').sort()).toEqual(
    [fixture.propertyA.id, fixture.propertyB.id].sort(),
  );
  expect(multiUrl.searchParams.has('unit_id')).toBe(false);

  const metrics = page.locator('.financial-workspace__metrics');
  await expect(metrics).toContainText(moneyDe(3000n));
  await expect(metrics).toContainText(moneyDe(5000n));
  await expect(metrics).toContainText(moneyDe(-2000n));
  await expect(metrics).toContainText('56');
  await expect(metrics).toContainText('4');

  const categoryCard = page.locator('.financial-workspace__analysis-card').filter({ hasText: 'Kostenarten' });
  await expect(categoryCard).toContainText(fixture.categoryCent.name);
  await expect(categoryCard).toContainText(moneyDe(30n));
  await expect(categoryCard).toContainText(fixture.categoryExpense.name);
  await expect(categoryCard).toContainText(moneyDe(5000n));

  const monthCard = page.locator('.financial-workspace__analysis-card').filter({ hasText: 'Monate' });
  await expect(monthCard).toContainText('2026-01');
  await expect(monthCard).toContainText(moneyDe(2830n));
  await expect(monthCard).toContainText('2026-02');
  await expect(monthCard).toContainText(moneyDe(-4830n));

  const locationCard = page.locator('.financial-workspace__analysis-card').filter({ hasText: 'Objekte und Einheiten' });
  await expect(locationCard).toContainText(`${fixture.propertyA.name} · ${fixture.unitA.label}`);
  await expect(locationCard).toContainText(`${fixture.propertyB.name} · Ohne Einheit`);

  const sources = page.locator('.financial-workspace__sources');
  expect(firstSourcesUrl.searchParams.get('source_hash')).toBe(multiJson.source_hash);
  expect(firstSourcesUrl.searchParams.get('account_id')).toBe(fixture.account.id);
  expect(firstSourcesUrl.searchParams.get('basis')).toBe('confirmed_cash');
  expect(firstSourcesUrl.searchParams.get('as_of')).toBe('2026-02-28');
  expect(firstSources.source_hash).toBe(multiJson.source_hash);
  expect(firstSources.source_count).toBe(56);
  expect(firstSources.excluded_count).toBe(4);
  expect(firstSources.items).toHaveLength(50);
  expect(new Set(firstSources.items.map(item => item.id)).size).toBe(50);
  await expect(sourceTable(page).locator('tbody tr')).toHaveCount(50);
  const receiptRow = sourceTable(page).getByRole('row').filter({ hasText: fixture.formula.payment_text });
  await expect(receiptRow).toContainText('Belegreferenz');
  await expect(receiptRow.getByRole('link')).toHaveCount(0);
  await sources.locator('.financial-workspace__table-scroll').focus();
  await expect(sources.locator('.financial-workspace__table-scroll')).toBeFocused();
  await expect(sources.locator('a')).toHaveCount(0);

  const nextRequest = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/reports/cash/sources'
      && url.searchParams.has('after')
      && response.status() === 200;
  });
  await sources.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  const nextResponse = await nextRequest;
  const nextJson = await nextResponse.json();
  const nextUrl = new URL(nextResponse.url());
  expect(nextUrl.searchParams.get('source_hash')).toBe(firstSources.source_hash);
  expect(nextJson.source_hash).toBe(firstSources.source_hash);
  expect(nextJson.source_count).toBe(firstSources.source_count);
  expect(nextJson.excluded_count).toBe(firstSources.excluded_count);
  expect(nextJson.items).toHaveLength(10);
  expect(nextJson.items.some(item => firstSources.items.some(first => first.id === item.id))).toBe(false);
  expect(nextUrl.searchParams.get('portfolio_id')).toBe(fixture.visiblePortfolio.id);
  expect(nextUrl.searchParams.getAll('property_ids').sort()).toEqual(
    [fixture.propertyA.id, fixture.propertyB.id].sort(),
  );
  await expect(sourceTable(page).locator('tbody tr')).toHaveCount(10);
  await expect(sourceTable(page)).toContainText(`FW ${fixture.suffix} expense feb 20`);

  const previousRequest = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/reports/cash/sources'
      && !url.searchParams.has('after')
      && url.searchParams.get('source_hash') === firstSources.source_hash
      && response.status() === 200;
  });
  await sources.getByRole('button', { name: 'Vorherige Seite', exact: true }).click();
  const previousJson = await (await previousRequest).json();
  expect(previousJson.items.map(item => item.id)).toEqual(firstSources.items.map(item => item.id));
  await expect(sourceTable(page).locator('tbody tr')).toHaveCount(50);

  const addedAfterReport = await create(page, fixture.owner, '/bookings', {
    account_id: fixture.account.id,
    category_id: fixture.categoryRent.id,
    property_id: fixture.propertyA.id,
    unit_id: fixture.unitA.id,
    booking_date: '2026-01-05',
    amount: 9.99,
    status: 'confirmed',
    payment_text: `FW ${fixture.suffix} source-hash mutation`,
  });

  const conflictResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/reports/cash/sources'
      && response.request().method() === 'GET'
      && response.status() === 409);
  await sources.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  const conflict = await conflictResponse;
  expect(await conflict.text()).toContain('Buchungsquellen haben sich geändert');
  await expect(page.getByText('Die Buchungsquellen haben sich geändert.', { exact: true })).toBeVisible();
  await expect(metrics).toContainText(moneyDe(3000n));
  await expect(page.getByText(fixture.visiblePortfolio.name, { exact: true })).toBeVisible();

  const refreshedReport = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/reports/cash' && response.status() === 200);
  await page.getByRole('button', { name: 'Aktuelle Buchungsquellen neu laden', exact: true }).click();
  const refreshed = await refreshedReport;
  const refreshedJson = await refreshed.json();
  expect(refreshedJson.income).toBe('39.99');
  expect(refreshedJson.expense).toBe('50.00');
  expect(refreshedJson.net).toBe('-10.01');
  await expect(metrics).toContainText(moneyDe(3999n));
  await expect(metrics).toContainText(moneyDe(-1001n));

  const csvRequestPromise = page.waitForRequest(request =>
    new URL(request.url()).pathname === '/api/v1/reports/cash/export.csv');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Vollständiges CSV', exact: true }).click();
  const [csvRequest, download] = await Promise.all([csvRequestPromise, downloadPromise]);
  const csvUrl = new URL(csvRequest.url());
  expect(csvUrl.searchParams.has('after')).toBe(false);
  expect(csvUrl.searchParams.has('source_hash')).toBe(false);
  expect(csvUrl.searchParams.get('portfolio_id')).toBe(fixture.visiblePortfolio.id);
  expect(csvUrl.searchParams.getAll('property_ids').sort()).toEqual(
    [fixture.propertyA.id, fixture.propertyB.id].sort(),
  );
  expect(download.suggestedFilename()).toBe('zahlungsquellen.csv');
  const csv = (await readFile(await download.path(), 'utf8')).replace(/^\uFEFF/, '');
  const csvLines = csv.trimEnd().split('\r\n');
  expect(csvLines).toHaveLength(fixture.visible.length + 2);
  for (const row of [...fixture.visible, { id: addedAfterReport.id }]) expect(csv).toContain(row.id);
  expect(csv).not.toContain(fixture.hiddenBooking.id);
  expect(csv).toContain(fixture.unconfirmed.id);
  expect(csv).toContain(fixture.cancelled.id);
  expect(csv).toContain(fixture.afterCutoffA.id);
  expect(csv).toContain(fixture.afterCutoffB.id);
  expect(csv).toContain(`'=SUM(2,3) FW ${fixture.suffix} protected csv`);

  for (const [width, height] of [[1440, 1000], [360, 844], [320, 844]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(page.getByRole('button', { name: 'Auswertung anwenden', exact: true })).toBeVisible();
    await expect(page.locator('.financial-workspace__table-scroll')).toBeVisible();
    const screenshot = testInfo.outputPath(`financial-workspace-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`FinancialWorkspace ${width}px`, { path: screenshot, contentType: 'image/png' });
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel('Grundlage', { exact: true }).selectOption('recorded_bookings');
  const recordedResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/reports/cash' && response.status() === 200);
  await apply.click();
  const recorded = await recordedResponse;
  const recordedJson = await recorded.json();
  expect(recordedJson.income).toBe('44.99');
  expect(recordedJson.expense).toBe('50.00');
  expect(recordedJson.net).toBe('-5.01');
  expect(recordedJson.source_count).toBe(58);
  expect(recordedJson.excluded_count).toBe(3);

  const grantChange = await page.request.patch('/api/v1/auth/users/' + fixture.reader.id, {
    headers: fixture.owner,
    data: { portfolio_access: 'selected', portfolio_ids: [] },
  });
  expect(grantChange.status(), await grantChange.text()).toBe(200);

  await apply.click();
  await expect(metrics).toHaveCount(0);
  await expect(page.getByText(fixture.visiblePortfolio.name, { exact: true })).toHaveCount(0);

  const scopedPortfolio = await page.request.get(
    `/api/v1/workflow-references/portfolios?selected_id=${encodeURIComponent(fixture.visiblePortfolio.id)}&page_size=25`,
    { headers: fixture.readerHeaders },
  );
  expect(scopedPortfolio.status(), await scopedPortfolio.text()).toBe(200);
  const scopedJson = await scopedPortfolio.json();
  expect(scopedJson.selected).toBeNull();
  expect(scopedJson.items.some(item => item.id === fixture.visiblePortfolio.id)).toBe(false);

  const directCash = await page.request.get(
    `/api/v1/reports/cash?portfolio_id=${encodeURIComponent(fixture.visiblePortfolio.id)}&basis=confirmed_cash&as_of=2026-02-28`,
    { headers: fixture.readerHeaders },
  );
  expect([403, 404]).toContain(directCash.status());
});
