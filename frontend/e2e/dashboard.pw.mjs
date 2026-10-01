import { test, expect } from '@playwright/test';

test('dashboard: actual SQL figures, six reports, mobile layouts and dark presentation', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const get = async path => {
    const response = await page.request.get(`/api/v1${path}`, { headers });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const [stats, units, aging, locale] = await Promise.all([get('/dashboard/stats'), get('/units?limit=1000'), get('/reports/receivables-aging'), page.request.get('/i18n/de-DE').then(response => response.json())]);
  const dashboard = page.locator('.dashboard-home');
  const translate = key => key.split('.').reduce((value, segment) => value?.[segment], locale);
  const money = value => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(value);
  await expect(dashboard.getByRole('heading', { name: 'Verwaltung im Überblick', level: 1 })).toBeVisible();
  await expect(dashboard.getByRole('article', { name: 'Immobilien', exact: true })).toContainText(String(stats.property_count));
  const occupied = units.filter(unit => ['occupied', 'rented'].includes(unit.status)).length;
  await expect(dashboard.getByRole('article', { name: 'Vermietete Einheiten' })).toContainText(`${occupied} / ${units.length}`);
  await expect(dashboard.getByRole('article', { name: 'Offene Beträge' })).toContainText(money(aging.openTotal));
  await expect(dashboard.getByRole('alert')).toHaveCount(0);
  const attach = async name => {
    const path = testInfo.outputPath(`${name}.png`);
    await page.screenshot({ path, fullPage: true });
    await testInfo.attach(name, { path, contentType: 'image/png' });
  };
  await attach('dashboard-work-desktop');
  await dashboard.getByRole('tab', { name: 'Auswertungen', exact: true }).click();
  await expect(dashboard.locator('.dashboard-home-report')).toHaveCount(6);
  await expect(dashboard.getByRole('alert')).toHaveCount(0);
  const report = dashboard.locator('.dashboard-home-report').filter({ has: page.getByRole('heading', { name: translate('pages.dashboard.cashflow'), exact: true }) });
  await report.getByText('Werte als Tabelle anzeigen', { exact: true }).click();
  const cashflow = await get('/reports/cashflow');
  await expect(report.getByRole('table')).toContainText(money(cashflow.netTotal));
  await expect.poll(() => dashboard.locator('.recharts-surface').count()).toBeGreaterThanOrEqual(4);
  await attach('dashboard-analysis-desktop');
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await attach('dashboard-analysis-dark');
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await testInfo.attach(`layout-${width}`, { body: JSON.stringify(await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth, dashboard: document.querySelector('.dashboard-home').getBoundingClientRect().toJSON(), outside: [...document.querySelectorAll('body *')].filter(element => !element.closest('.dashboard-home-table-scroll') && element.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 15).map(element => ({ tag: element.tagName, class: element.className.baseVal ?? element.className, right: element.getBoundingClientRect().right })) })), null, 2), contentType: 'application/json' });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await attach(`dashboard-analysis-${width}`);
    await dashboard.getByRole('tab', { name: 'Arbeitszentrale', exact: true }).click();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await attach(`dashboard-work-${width}`);
    await dashboard.getByRole('tab', { name: 'Auswertungen', exact: true }).click();
  }
  expect(errors).toEqual([]);
});
