import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
}

async function sessionHeaders(page) {
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

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
