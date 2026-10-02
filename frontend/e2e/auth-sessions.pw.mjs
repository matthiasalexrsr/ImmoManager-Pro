import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page, account = { username: 'demo', password: 'Demo1234' }) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(account.username);
  await page.getByLabel('Passwort', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
}

async function sessionHeaders(page) {
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

test('a stale renderer cache adopts the committed pair without replaying a consumed refresh', async ({ page, context }) => {
  await login(page);
  const tab = await context.newPage();
  const errors = [];
  tab.on('pageerror', error => errors.push(error.message));
  try {
    await tab.goto('/settings'); await germanWorkspaceReady(tab);
    expect(await tab.evaluate(() => typeof navigator.locks?.request === 'function' && typeof indexedDB.open === 'function')).toBe(true);
    // Model delayed cross-renderer Storage visibility. Own writes still update
    // this renderer immediately; no API responses or backend behavior are mocked.
    await tab.evaluate(() => {
      const access = `${localStorage.getItem('access_token')}.invalid`;
      localStorage.setItem('access_token', access);
      sessionStorage.setItem('synthetic-stale-session', JSON.stringify({
        access_token: access, refresh_token: localStorage.getItem('refresh_token'),
      }));
    });
    await tab.addInitScript(() => {
      const saved = sessionStorage.getItem('synthetic-stale-session');
      if (!saved) return;
      let cached = JSON.parse(saved);
      const getItem = Storage.prototype.getItem;
      const setItem = Storage.prototype.setItem;
      Storage.prototype.getItem = function (key) {
        if (this === localStorage && cached && Object.hasOwn(cached, key)) return cached[key];
        return getItem.call(this, key);
      };
      Storage.prototype.setItem = function (key, value) {
        if (this === localStorage && key === 'access_token') cached = null;
        return setItem.call(this, key, value);
      };
    });
    let rotations = 0;
    let releaseSecond;
    const firstRotation = new Promise(resolve => { releaseSecond = resolve; });
    context.on('request', request => {
      if (new URL(request.url()).pathname === '/api/v1/auth/refresh' && request.method() === 'POST') rotations++;
    });
    context.on('response', async response => {
      if (new URL(response.url()).pathname === '/api/v1/auth/refresh' && response.status() === 200) {
        await response.finished(); releaseSecond();
      }
    });
    let delayed = false;
    await context.route('**/api/v1/auth/me', async route => {
      if (route.request().frame().page() === tab && !delayed) { delayed = true; await firstRotation; }
      await route.continue();
    });
    await Promise.all([page.goto('/settings'), tab.reload()]);
    await Promise.all([germanWorkspaceReady(page), germanWorkspaceReady(tab)]);
    expect(delayed).toBe(true);
    expect(rotations).toBe(1);
    for (const current of [page, tab]) {
      expect((await current.request.get('/api/v1/auth/me', { headers: await sessionHeaders(current) })).status()).toBe(200);
    }
    expect(errors).toEqual([]);
  } finally { await context.unroute('**/api/v1/auth/me'); await tab.close(); }
});

test('an open owner tab drops private state when another tab changes actor and logs out', async ({ page, context }) => {
  await login(page);
  const ownerHeaders = await sessionHeaders(page);
  const name = `Session Actor ${Date.now()}`;
  const account = { username: `session-actor-${Date.now()}`, password: 'Synthetic Actor Password 2026' };
  const created = await page.request.post('/api/v1/auth/users', {
    headers: ownerHeaders,
    data: { ...account, email: `${account.username}@example.com`, full_name: name,
      role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] },
  });
  expect(created.status()).toBe(201);
  const nextUser = await created.json();
  const properties = await page.request.get('/api/v1/properties', { headers: ownerHeaders });
  expect(properties.status()).toBe(200);
  const previousProperty = (await properties.json())[0];
  expect(previousProperty).toBeTruthy();
  await page.goto('/properties'); await germanWorkspaceReady(page);
  await expect(page.getByText(previousProperty.name, { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Immobilie anlegen', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  const other = await context.newPage();
  const errors = []; other.on('pageerror', error => errors.push(error.message));
  try {
    await login(other, account);
    await expect(page.getByText(name, { exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Immobilie anlegen', exact: true })).toHaveCount(0);
    await expect(page.getByText('Ihr Bestand beginnt hier', { exact: true })).toBeVisible();
    await expect(page.getByText(previousProperty.name, { exact: true })).toHaveCount(0);
    const currentHeaders = await sessionHeaders(page);
    const current = await page.request.get('/api/v1/auth/me', { headers: currentHeaders });
    expect(current.status()).toBe(200); expect((await current.json()).id).toBe(nextUser.id);
    expect(await (await page.request.get('/api/v1/properties', { headers: currentHeaders })).json()).toEqual([]);
    await other.getByRole('button', { name: 'Abmelden', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(other).toHaveURL(/\/login$/);
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeNull();
    expect((await page.request.get('/api/v1/auth/me', { headers: currentHeaders })).status()).toBe(401);
    expect(errors).toEqual([]);
  } finally { await other.close(); }
});

test('two tabs coordinate one refresh and own-session revocation immediately denies the other browser', async ({ page, context, browser }, testInfo) => {
  test.setTimeout(100_000);
  await login(page);
  const tab = await context.newPage();
  const errors = [];
  tab.on('pageerror', error => errors.push(error.message));
  await tab.goto('/settings'); await germanWorkspaceReady(tab);
  const invalid = await page.evaluate(() => {
    const value = `${localStorage.getItem('access_token')}.invalid`;
    localStorage.setItem('access_token', value);
    return value;
  });
  let rotations = 0;
  context.on('request', request => {
    if (new URL(request.url()).pathname === '/api/v1/auth/refresh' && request.method() === 'POST') rotations++;
  });
  const held = [];
  await context.route('**/api/v1/auth/me', async route => {
    if (route.request().headers().authorization === `Bearer ${invalid}` && held.length < 2) {
      held.push(route);
      if (held.length === 2) await Promise.all(held.map(request => request.continue()));
    } else await route.continue();
  });
  await Promise.all([page.goto('/settings'), tab.reload()]);
  await Promise.all([germanWorkspaceReady(page), germanWorkspaceReady(tab)]);
  expect(held).toHaveLength(2);
  expect(rotations).toBe(1);
  await context.unroute('**/api/v1/auth/me');
  const firstHeaders = await sessionHeaders(page);
  expect((await page.request.get('/api/v1/auth/me', { headers: firstHeaders })).status()).toBe(200);

  const otherContext = await browser.newContext({
    baseURL: process.env.IMMO_E2E_URL, locale: 'de-DE', timezoneId: 'Europe/Berlin',
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
  });
  const other = await otherContext.newPage();
  try {
    await login(other);
    const otherHeaders = await sessionHeaders(other);
    await page.getByRole('button', { name: 'Anmeldung & Sitzungen', exact: true }).click();
    const section = page.getByRole('region', { name: 'Meine Sitzungen', exact: true });
    await section.getByRole('button', { name: 'Sitzungen aktualisieren', exact: true }).click();
    const otherCard = section.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'Firefox / Linux', exact: true }) });
    await expect(otherCard).toHaveCount(1);
    await otherCard.getByRole('button', { name: 'Sitzung beenden', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
    await expect(otherCard.getByText('Beendet', { exact: true })).toBeVisible();
    expect((await other.request.get('/api/v1/auth/me', { headers: otherHeaders })).status()).toBe(401);
    const refresh = await other.evaluate(() => localStorage.getItem('refresh_token'));
    expect((await other.request.post('/api/v1/auth/refresh', { data: { refresh_token: refresh } })).status()).toBe(401);
    expect((await page.request.get('/api/v1/auth/me', { headers: firstHeaders })).status()).toBe(200);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await testInfo.attach('own-sessions-mobile', { body: await page.screenshot(), contentType: 'image/png' });
    await section.getByRole('button', { name: 'Diese Anmeldung beenden', exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeNull();
    expect((await page.request.get('/api/v1/auth/me', { headers: firstHeaders })).status()).toBe(401);
    expect(errors).toEqual([]);
  } finally { await otherContext.close(); await tab.close(); }
});
