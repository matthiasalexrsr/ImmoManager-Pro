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

async function seed(page, headers) {
  const suffix = randomUUID().slice(0, 8);
  const create = async (path, data) => {
    const response = await page.request.post('/api/v1' + path, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const portfolio = await create('/portfolios', { name: 'Saldoquellen ' + suffix });
  const account = await create('/accounts', { portfolio_id: portfolio.id, name: 'Quellenkonto ' + suffix, account_type: 'Girokonto', opening_balance: 100, balance: 120 });
  const other = await create('/accounts', { portfolio_id: portfolio.id, name: 'Anderes Konto ' + suffix, account_type: 'Girokonto', opening_balance: 0, balance: 0 });
  const rows = [];
  for (const [amount, status, day] of [[25, 'booked', '2026-01-10'], [-7, 'open', '2026-01-11'], [9.99, 'confirmed', '2027-02-01']]) {
    rows.push(await create('/bookings', { account_id: account.id, amount, status, booking_date: day, payment_text: `Saldoquelle ${suffix} ${status}` }));
  }
  await create('/bookings', { account_id: other.id, amount: 999, booking_date: '2026-01-01', payment_text: 'Andere Kontobewegung ' + suffix });
  return { suffix, portfolio, account, other, rows, create };
}

async function openSource(page, account) {
  await page.getByRole('button', { name: 'Kontosaldo nachvollziehen', exact: true }).click();
  const panel = page.locator('.account-balance-panel');
  await panel.getByLabel('Konto suchen', { exact: true }).fill(account.name);
  await expect(panel.getByRole('option', { name: account.name, exact: true })).toBeAttached();
  await panel.getByRole('combobox', { name: 'Konto', exact: true }).selectOption(account.id);
  await expect(panel.locator('.account-balance-calculated strong')).toHaveText('127,99 €');
  return panel;
}

test('cash balance evidence: exact persisted sources, inclusive cutoff, real account drilldown and mobile/dark view', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const headers = await login(page);
  const { account, rows } = await seed(page, headers);
  const summaryRequests = [];
  page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/balance-summary')) summaryRequests.push(request); });
  await page.goto('/accounts');
  await expect(page.getByRole('heading', { name: 'Konten', exact: true, level: 1 })).toBeVisible();
  expect(summaryRequests).toHaveLength(0);
  const panel = await openSource(page, account);
  expect(summaryRequests).toHaveLength(1);
  await expect(panel.locator('.account-balance-comparison strong')).toHaveText('120,00 €');
  await expect(panel.locator('.account-balance-difference strong')).toHaveText('7,99 €');
  await expect(panel).toContainText('Alle gespeicherten Buchungen, auch zukünftige');
  await expect(panel.getByRole('table')).toContainText(rows[0].id);
  await expect(panel.getByRole('table')).toContainText(rows[1].id);
  await expect(panel.getByRole('table')).toContainText(rows[2].id);
  await panel.getByLabel('Buchungen bis einschließlich', { exact: true }).fill('2026-01-31');
  await panel.getByRole('button', { name: 'Zeitraum anwenden', exact: true }).click();
  await expect(panel.locator('.account-balance-calculated strong')).toHaveText('118,00 €');
  await expect(panel.locator('.account-balance-difference strong')).toHaveText('−2,00 €');
  await expect(panel.getByRole('table')).not.toContainText(rows[2].id);
  await panel.getByText('Herkunftsnachweis', { exact: true }).click();
  await expect(panel.locator('.account-balance-proof')).toContainText('2026-01-10 → 2026-01-11');
  await panel.getByRole('button', { name: 'Prüfbefunde (0)', exact: true }).click();
  await expect(panel).toContainText('Keine ungültigen Betragsquellen gefunden. Dies bestätigt keine Übereinstimmung mit der Bank.');
  const stored = await page.request.get('/api/v1/accounts/' + account.id, { headers });
  expect((await stored.json()).balance).toBe(120);

  for (const theme of ['light', 'dark']) {
    await page.evaluate(value => document.documentElement.setAttribute('data-theme', value), theme);
    await page.setViewportSize({ width: 320, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(panel.locator('.account-balance-calculated strong')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    const screenshot = testInfo.outputPath(`account-balance-${theme}-320.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`account-balance-${theme}-320`, { path: screenshot, contentType: 'image/png' });
  }
  const firstPage = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/bookings/page');
  await panel.getByRole('link', { name: 'Buchungen dieses Kontos öffnen', exact: true }).click();
  await expect(page).toHaveURL(new RegExp('/bookings\\?account_id=' + account.id + '$'));
  const response = await firstPage;
  expect(new URL(response.url()).searchParams.get('account_id')).toBe(account.id);
  expect((await response.json()).items.map(item => item.id).sort()).toEqual(rows.map(item => item.id).sort());
  await expect(page.getByRole('table')).not.toContainText('Andere Kontobewegung');
  await page.reload();
  await expect(page.getByRole('table')).toContainText(rows[0].payment_text);
  await expect(page.getByText('Aktiver Kontofilter:', { exact: false })).toContainText(account.id);
});

test('selected reader sees authorized cash evidence but grant withdrawal clears the result and forbids direct IDs', async ({ page }) => {
  test.setTimeout(120_000);
  const owner = await login(page);
  const seeded = await seed(page, owner);
  const hiddenPortfolio = await seeded.create('/portfolios', { name: 'Verdeckte Saldoquelle ' + seeded.suffix });
  const hiddenAccount = await seeded.create('/accounts', { portfolio_id: hiddenPortfolio.id, name: 'Verdecktes Quellenkonto', account_type: 'Girokonto' });
  const username = 'cash-reader-' + seeded.suffix;
  const password = 'Synthetic reader passphrase123!';
  const reader = await seeded.create('/auth/users', { username, email: `${username}@example.test`, full_name: 'Synthetic cash reader',
    password, role: 'readonly', portfolio_access: 'selected', portfolio_ids: [seeded.portfolio.id] });
  const preferencesLogin = await page.request.post('/api/v1/auth/login', { data: { username, password } });
  expect(preferencesLogin.status()).toBe(200);
  const readerHeaders = { Authorization: 'Bearer ' + (await preferencesLogin.json()).access_token };
  expect((await page.request.put('/api/v1/auth/users/me/preferences', { headers: readerHeaders, data: { locale: 'de-DE', theme: 'light' } })).status()).toBe(200);
  await page.evaluate(() => { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); });
  await login(page, username, password);
  await page.goto('/accounts');
  const panel = await openSource(page, seeded.account);
  await expect(panel.getByRole('button', { name: 'Kontowerte bearbeiten', exact: true })).toHaveCount(0);
  const forbidden = await page.request.get(`/api/v1/accounts/${hiddenAccount.id}/balance-summary`, { headers: readerHeaders });
  expect(forbidden.status()).toBe(404);
  expect(await forbidden.text()).not.toContain(hiddenAccount.name);
  const change = await page.request.patch('/api/v1/auth/users/' + reader.id, { headers: owner, data: { portfolio_access: 'selected', portfolio_ids: [] } });
  expect(change.status()).toBe(200);
  await panel.getByRole('button', { name: 'Quellen neu laden', exact: true }).click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel.locator('.account-balance-calculated')).toHaveCount(0);
  const direct = await page.request.get(`/api/v1/accounts/${seeded.account.id}/balance-sources`, { headers: readerHeaders });
  expect(direct.status()).toBe(404);
  expect(await direct.text()).not.toContain(seeded.rows[0].id);
});
