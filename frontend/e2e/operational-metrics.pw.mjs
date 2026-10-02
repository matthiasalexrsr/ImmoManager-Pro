import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('installation operator reads real process metrics and responsive status with explicit refresh', async ({ page }, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  const endpoint = '/api/v1/admin/operational-metrics';
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const before = await page.request.get(endpoint, { headers });
  expect(before.status(), await before.text()).toBe(200);
  const initial = await before.json();
  expect(initial).toMatchObject({ scope: 'process_worker', persistent: false, database: { state: 'connected', backend: 'sqlite', persistent: true } });
  for (let index = 0; index < 3; index += 1) {
    const rejected = await page.request.post(`/api/v1/metrics-private-unknown-${index}`);
    expect(rejected.status()).toBe(405);
  }
  const observed = await page.request.get(endpoint, { headers });
  const counters = await observed.json();
  expect(counters.requests.completed).toBeGreaterThan(initial.requests.completed);
  expect(counters.requests.series.some(row => row.group === 'unmatched' && row.outcome === 'client_error' && row.count >= 3)).toBe(true);
  expect(JSON.stringify(counters)).not.toContain('metrics-private-unknown');
  await page.goto('/settings');
  await page.getByRole('button', { name: 'System', exact: true }).click();
  const section = page.getByRole('region', { name: 'Betriebszustand', exact: true });
  await expect(section.getByText('Datenbank erreichbar', { exact: true })).toBeVisible();
  await expect(section.getByRole('table')).toBeVisible();
  await expect(section).toContainText('mehrere Worker werden nicht zusammengezählt');
  const refreshed = page.waitForResponse(response => new URL(response.url()).pathname === endpoint);
  await section.getByRole('button', { name: 'Status aktualisieren', exact: true }).click();
  const response = await refreshed;
  expect(response.status(), await response.text()).toBe(200);
  await expect(section).toHaveAttribute('aria-busy', 'false');
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await section.scrollIntoViewIfNeeded();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(section.getByRole('button', { name: 'Status aktualisieren', exact: true })).toBeVisible();
  }
  const tableArea = section.getByRole('region', { name: 'Anfragen nach Verwaltungsbereich', exact: true });
  await tableArea.focus();
  await tableArea.press('ArrowRight');
  await expect.poll(() => tableArea.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath('operational-status-mobile.png'), fullPage: true });
  const denied = await page.request.get(endpoint);
  expect(denied.status()).toBe(401);
  expect(await denied.text()).not.toContain('series');
});
