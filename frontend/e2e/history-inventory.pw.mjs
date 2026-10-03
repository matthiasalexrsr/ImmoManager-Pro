import { readFile, writeFile } from 'node:fs/promises';
import { test, expect } from './demoFixtures.mjs';
import { login, nativeApi } from './dashboardFixture.mjs';

test('History: native 10002 complete export, reached rows, mobile detail and actual grants', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const box = JSON.parse(await readFile(process.env.IMMO_E2E_HISTORY_FIXTURE, 'utf8'));
  expect(box.basis).toBe('native-owned-history-stock');
  const loginResponse = await page.request.post('/api/v1/auth/login', { data: { username: 'demo', password: 'Demo1234' } });
  expect(loginResponse.status()).toBe(200);
  const owner = nativeApi(page, { Authorization: `Bearer ${(await loginResponse.json()).access_token}` });
  const account = await owner('/auth/users', { username: `history-${box.tag}`, email: `history-${box.tag}@example.test`,
    full_name: 'Synthetic history reader', password: 'Synthetic B2 Dashboard Passphrase 2026!', role: 'readonly',
    portfolio_access: 'selected', portfolio_ids: [box.portfolio_id] });
  await login(page, account);
  const reads = []; page.on('request', request => { if (request.method() === 'GET') reads.push(new URL(request.url()).pathname + new URL(request.url()).search); });
  await page.goto('/history');
  const view = page.locator('.history-inventory');
  await expect(view.getByText('10.002', { exact: true })).toBeVisible();
  await expect(view.getByRole('row')).toHaveCount(26);
  await view.getByText('Werte und Grund anzeigen', { exact: true }).first().click();
  await expect(view.getByText(box.long_value.trim(), { exact: true })).toBeVisible();
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`history-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await view.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
  await expect(view.getByText('Seite 2', { exact: true })).toBeVisible();
  expect(reads.some(path => path.startsWith('/api/v1/history/inventory/page?') && path.includes('cursor='))).toBe(true);
  for (const number of [100, 1000, 10000]) {
    await view.getByRole('searchbox', { name: 'Historie durchsuchen', exact: true }).fill(`${box.prefix}${String(number).padStart(6, '0')}`);
    await expect(view.getByRole('row')).toHaveCount(2);
    await view.getByText('Werte und Grund anzeigen', { exact: true }).click();
    await expect(view.getByText(`history-${box.tag}-${String(number).padStart(6, '0')}`, { exact: true })).toBeVisible();
  }
  await view.getByRole('button', { name: 'Filter zurücksetzen', exact: true }).click();
  await expect(view.getByText('10.002', { exact: true })).toBeVisible();
  const pending = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Alle gefilterten Änderungen exportieren', exact: true }).click();
  const downloaded = await pending; const path = await downloaded.path();
  expect(path).toBeTruthy(); const csv = await readFile(path, 'utf8');
  const lines = csv.replace(/^\uFEFF/, '').trimEnd().split('\r\n');
  expect(lines).toHaveLength(box.count + 1);
  const identifiers = lines.slice(1).map(line => line.split(';')[0]);
  expect(new Set(identifiers).size).toBe(box.count);
  expect(identifiers[0]).toBe(`history-${box.tag}-010001`); expect(identifiers.at(-1)).toBe(`history-${box.tag}-000000`);
  expect(csv).toContain("'=1+1");
  expect(reads.some(path => path === '/api/v1/history' || path.includes('/history?limit=500'))).toBe(false);
  await owner(`/auth/users/${account.id}`, { portfolio_access: 'selected', portfolio_ids: [] }, 'PATCH', 200);
  await view.getByRole('button', { name: 'Aktualisieren', exact: true }).click();
  await expect(view.getByText('Keine passenden Änderungen auf dieser Seite.', { exact: true })).toBeVisible();
  await expect(view.getByRole('row')).toHaveCount(0);
  await expect(view.getByText('0', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('history-native-grants-cleared.png'), fullPage: true });
  await writeFile(testInfo.outputPath('history-proof.json'), JSON.stringify({ basis: box.basis, count: identifiers.length,
    reachedPositions: [101, 1001, 10001], originalIdsUnique: new Set(identifiers).size, nativeReads: reads,
    actualRevoke: 'same actor empty portfolio grants', finalCount: 0 }, null, 2));
});
