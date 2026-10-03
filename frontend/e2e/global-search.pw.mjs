import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('complete global keyword search: later pages, recovery, keyboard and small screens', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const create = async (path, data) => {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const term = `Suchbestand ${randomUUID().slice(0, 8)}`;
  const portfolio = await create('/portfolios', { name: term });
  for (let index = 0; index < 101; index += 1) {
    await create('/properties', { name: `${term} ${index}`, portfolio_id: portfolio.id, property_type: 'residential', city: 'Saarbrücken' });
  }
  const search = page.getByRole('search');
  const input = search.getByRole('combobox');
  await input.fill(term);
  await expect(search.getByRole('option')).toHaveCount(50);
  await search.getByRole('button', { name: 'Weitere Treffer', exact: true }).click();
  await expect(search.getByRole('option')).toHaveCount(50);
  await expect(search.getByText('Seite 2', { exact: true })).toBeVisible();

  let failedCursor;
  await page.route('**/api/v1/search/page?*', async route => {
    const cursor = new URL(route.request().url()).searchParams.get('after');
    if (cursor) {
      failedCursor = cursor;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Suchdienst vorübergehend nicht erreichbar' }) });
    } else await route.continue();
  });
  await search.getByRole('button', { name: 'Weitere Treffer', exact: true }).click();
  await expect(search.getByRole('alert')).toContainText('Suchdienst vorübergehend nicht erreichbar');
  expect(failedCursor).toBeTruthy();
  await expect(search.getByRole('option')).toHaveCount(0);
  await expect(input).toHaveValue(term);
  await page.unroute('**/api/v1/search/page?*');
  const recovered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/search/page' && new URL(response.url()).searchParams.get('after') === failedCursor && response.status() === 200);
  await search.getByRole('button', { name: 'Erneut versuchen', exact: true }).click();
  await recovered;
  await expect(search.getByRole('option')).toHaveCount(1);
  await expect(search.getByText('Seite 3', { exact: true })).toBeVisible();

  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width < 400 ? 844 : 1000 });
    await input.focus();
    await expect(search.getByRole('option')).toHaveCount(1);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const bounds = await search.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    const screenshot = testInfo.outputPath(`global-search-${width}.png`);
    await page.screenshot({ path: screenshot });
    await testInfo.attach(`global-search-${width}`, { path: screenshot, contentType: 'image/png' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await input.press('ArrowDown');
  await expect(search.getByRole('option')).toHaveAttribute('aria-selected', 'true');
  await input.press('Enter');
  await expect(page).toHaveURL(/\/properties\/[^/]+$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(term);
});
