import { test, expect } from './demoFixtures.mjs';
import { addDays, capture, cursorNames, dashboard, familyLabels, fixture, hintPanel, login, pathIs, proof } from './dashboardFixture.mjs';

test.skip(!process.env.IMMO_E2E_DASHBOARD_FIXTURE, 'B2 acceptance requires the opt-in --dashboard-fixture owned SQL seed');

test('B2: native 10001-unit full counts and three bounded keysets reach all real hints', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const box = await fixture(page, { large: true });
  const stockRequests = [];
  page.on('request', request => { const path = new URL(request.url()).pathname; if (request.method() === 'GET' && ['/api/v1/units', '/api/v1/tasks', '/api/v1/reports/contracts-expiring'].includes(path)) stockRequests.push(request.url()); });
  const api = await login(page, box.account); let actual = await api('/dashboard/stats?preview_limit=5');
  expect(actual.occupancy).toMatchObject(box.expected); expect(actual.unit_count).toBe(10001); expect(actual.property_count).toBe(1); expect(actual.portfolio_count).toBe(1);
  expect(await api(`/units/${box.lastUnit.id}`)).toMatchObject({ id: box.lastUnit.id, status: box.lastUnit.status });
  await expect(dashboard(page).getByRole('article', { name: 'Belegte Einheiten', exact: true })).toContainText('4.001 / 10.001');
  await expect(dashboard(page).getByRole('link', { name: 'Vertrag erstellen', exact: true })).toHaveCount(0);
  const ids = {}; const queries = [];
  for (const [family, title] of Object.entries(familyLabels)) {
    const seen = []; const panel = hintPanel(page, title);
    expect(actual.work_hints[family].total).toBe(13); await expect(panel).toContainText('13 insgesamt');
    for (;;) {
      const current = actual.work_hints[family]; expect(current.items.length).toBeLessThanOrEqual(5);
      for (const row of current.items) {
        expect(seen).not.toContain(row.id); seen.push(row.id);
        await expect(panel.getByText(family === 'expiring_contracts' ? row.contract_number : row.title, { exact: true })).toBeVisible();
      }
      if (!current.has_more) break;
      const responsePromise = page.waitForResponse(pathIs('/dashboard/stats'));
      const next = panel.getByRole('button', { name: 'Weiter', exact: true }); await next.focus(); await page.keyboard.press('Enter');
      const response = await responsePromise; expect(response.status(), await response.text()).toBe(200);
      const parameters = new URL(response.url()).searchParams; expect(parameters.get('as_of')).toBe(box.asOf); expect(parameters.get(cursorNames[family])).toBe(current.next_after); queries.push(parameters.toString());
      actual = await response.json(); expect(actual.occupancy).toMatchObject(box.expected); expect(actual.work_hints[family].total).toBe(13);
    }
    const expected = family === 'tasks' ? box.tasks : family === 'notifications' ? box.notifications : box.contracts;
    expect(seen.slice().sort()).toEqual(expected.map(row => row.id).sort()); ids[family] = seen;
  }
  expect(ids.tasks).toEqual(box.tasks.map(row => row.id));
  expect(ids.tasks.slice(-3).every(id => box.tasks.find(row => row.id === id).due_date === null)).toBe(true);
  expect(stockRequests).toEqual([]); expect(actual.billing_presence).toMatchObject({ basis: 'basic_presence_checks', complete_preflight: false });
  await capture(page, testInfo, 'B2-complete-work', hintPanel(page, familyLabels.tasks));
  await dashboard(page).getByRole('tab', { name: 'Auswertungen', exact: true }).click();
  await expect(dashboard(page).locator('.dashboard-home-report')).toHaveCount(6);
  const occupancy = hintPanel(page, 'Belegung');
  await occupancy.getByText('Werte als Tabelle anzeigen', { exact: true }).click(); await expect(occupancy.getByRole('table')).toContainText('4.001');
  await capture(page, testInfo, 'B2-analysis', occupancy);
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await capture(page, testInfo, 'B2-analysis-dark', occupancy);
  await proof(testInfo, 'B2-native-full-count-and-cursors', { knownFixtureCounts: box.expected, actualCount: actual.unit_count, ids, actualQueries: queries, forbiddenStockRequests: stockRequests });
});

test('B2: exact selected context, A to B cancellation and real role/grant 403 hide prior data', async ({ page }, testInfo) => {
  test.setTimeout(90_000); const box = await fixture(page, { role: 'verwalter' }); const api = await login(page, box.account);
  await expect(dashboard(page).getByRole('article', { name: 'Belegte Einheiten', exact: true })).toContainText('6 / 13');
  const readPaths = []; page.on('request', request => { if (request.method() === 'GET') readPaths.push(new URL(request.url()).pathname); });
  const first = box.tasks[0]; const second = box.tasks[1]; const firstPath = `/api/v1/tasks/${first.id}`;
  let release; let held;
  const wait = new Promise(resolve => { release = resolve; });
  await page.route(`**${firstPath}`, async route => { const response = await route.fetch(); expect(response.status()).toBe(200); held = await response.json(); await wait; if (!route.request().failure()) await route.fulfill({ response }); });
  await hintPanel(page, familyLabels.tasks).getByRole('button', { name: first.title, exact: true }).click(); await expect.poll(() => Boolean(held)).toBe(true);
  await hintPanel(page, familyLabels.tasks).getByRole('button', { name: second.title, exact: true }).click();
  const context = dashboard(page).getByRole('region', { name: 'Objektkontext', exact: true });
  const secondUnit = box.unitRows.find(row => row.id === second.unit_id);
  await expect(context.getByRole('link', { name: secondUnit.label, exact: true })).toHaveAttribute('href', `/units/${second.unit_id}`);
  release(); await page.unroute(`**${firstPath}`);
  await expect(context.getByText(first.title, { exact: true })).toHaveCount(0);
  expect(readPaths.filter(path => path === `/api/v1/units/${first.unit_id}`)).toHaveLength(0);
  expect(readPaths.filter(path => path === `/api/v1/units/${second.unit_id}`)).toHaveLength(1);
  expect(readPaths.filter(path => path === `/api/v1/properties/${box.property.id}`)).toHaveLength(1);
  expect(readPaths.some(path => path.startsWith('/api/v1/tenants'))).toBe(false);
  await capture(page, testInfo, 'B2-exact-context', context);
  await context.getByRole('button', { name: 'Kontext schließen', exact: true }).click();
  await expect(hintPanel(page, familyLabels.tasks).getByRole('button', { name: second.title, exact: true })).toBeFocused();
  const changed = await box.owner(`/auth/users/${box.account.id}`, { role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] }, 'PATCH', 200);
  expect(changed).toMatchObject({ role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] });
  // Cached manager controls trigger the actual now-forbidden audit GET. No
  // authority response or denial is fabricated by the browser harness.
  const denied = page.waitForResponse(pathIs('/audit')); await dashboard(page).getByRole('button', { name: 'Letzte Aktivitäten', exact: true }).click();
  const response = await denied; expect(response.status(), await response.text()).toBe(403);
  await expect(dashboard(page)).toContainText('Vorherige Daten werden ausgeblendet.');
  await expect(dashboard(page).getByRole('article')).toHaveCount(0); await expect(dashboard(page).getByText(box.property.name, { exact: true })).toHaveCount(0);
  const fresh = page.waitForResponse(pathIs('/auth/me')); await dashboard(page).getByRole('button', { name: 'Zugriff erneut prüfen', exact: true }).click();
  expect(await (await fresh).json()).toMatchObject({ role: 'readonly', portfolio_ids: [] });
  await expect(dashboard(page).getByRole('article', { name: 'Belegte Einheiten', exact: true })).toContainText('0 / 0');
  await expect(dashboard(page).getByRole('button', { name: 'Letzte Aktivitäten', exact: true })).toHaveCount(0);
  await expect(dashboard(page).getByRole('link', { name: 'Vertrag erstellen', exact: true })).toHaveCount(0);
  const after = await api('/dashboard/stats?preview_limit=5'); expect(after.unit_count).toBe(0); expect(after.work_hints.tasks.total).toBe(0);
  await capture(page, testInfo, 'B2-native-scope-hidden'); await proof(testInfo, 'B2-native-authority-context', { selectedTask: second.id, checkedParentReads: readPaths.filter(path => /\/(tasks|units|properties)\//.test(path)), actualDenial: response.status(), actualRole: changed.role, actualRemainingUnits: after.unit_count });
});

test('B2: real empty source, lost native response, explicit stale retry and actual cursor-binding 422', async ({ page }, testInfo) => {
  test.setTimeout(90_000); const box = await fixture(page, { units: 0, hints: 0, role: 'verwalter' });
  let lose = true; let disturbCursor = false; const nativeStatuses = [];
  await page.route('**/api/v1/dashboard/stats?*', async route => {
    const url = new URL(route.request().url());
    if (disturbCursor && url.searchParams.has('tasks_after')) {
      url.searchParams.set('as_of', addDays(url.searchParams.get('as_of'), 1));
      return route.continue({ url: url.href }); // Only the native request binding changes.
    }
    const response = await route.fetch(); nativeStatuses.push(response.status()); expect(response.status(), await response.text()).toBe(200);
    if (lose) await route.abort('failed'); else await route.fulfill({ response });
  });
  const api = await login(page, box.account);
  await expect(dashboard(page).getByRole('alert')).toBeVisible(); await expect(hintPanel(page, familyLabels.tasks).getByText('Keine offenen Aufgaben', { exact: true })).toHaveCount(0);
  await expect(dashboard(page).getByRole('article', { name: 'Belegte Einheiten', exact: true })).toContainText('—');
  lose = false; await dashboard(page).getByRole('alert').getByRole('button', { name: 'Erneut laden', exact: true }).click();
  await expect(dashboard(page).getByRole('article', { name: 'Belegte Einheiten', exact: true })).toContainText('0 / 0');
  await expect(hintPanel(page, familyLabels.tasks).getByText('Keine offenen Aufgaben', { exact: true })).toBeVisible();
  const empty = await api('/dashboard/stats?preview_limit=5'); expect(empty.unit_count).toBe(0); expect(empty.work_hints.tasks.total).toBe(0);
  lose = true; await dashboard(page).getByRole('button', { name: 'Aktualisieren', exact: true }).click(); await expect(dashboard(page).getByRole('alert')).toBeVisible();
  await expect(dashboard(page).getByText(/Älterer Stand von/)).toBeVisible(); await expect(hintPanel(page, familyLabels.tasks).getByText('Keine offenen Aufgaben', { exact: true })).toHaveCount(0);
  await capture(page, testInfo, 'B2-real-lost-summary-stale');
  lose = false; await dashboard(page).getByRole('alert').getByRole('button', { name: 'Erneut laden', exact: true }).click(); await expect(dashboard(page).getByText(/Älterer Stand von/)).toHaveCount(0);
  const property = await box.owner('/properties', { portfolio_id: box.portfolio.id, name: `B2 cursor property ${box.tag}`, property_type: 'residential' });
  for (let index = 0; index < 6; index++) await box.owner('/tasks', { title: `B2 native cursor task ${index} ${box.tag}`, property_id: property.id, due_date: box.asOf });
  await dashboard(page).getByRole('button', { name: 'Aktualisieren', exact: true }).click(); await expect(hintPanel(page, familyLabels.tasks)).toContainText('6 insgesamt');
  disturbCursor = true; const rejected = page.waitForResponse(response => pathIs('/dashboard/stats')(response) && response.status() === 422);
  await hintPanel(page, familyLabels.tasks).getByRole('button', { name: 'Weiter', exact: true }).click(); const response = await rejected;
  expect(response.status(), await response.text()).toBe(422); await expect(dashboard(page).getByRole('alert')).toContainText('Diese Seite kann nicht mehr geprüft werden.');
  disturbCursor = false; const restart = page.waitForResponse(pathIs('/dashboard/stats'));
  await dashboard(page).getByRole('alert').getByRole('button', { name: 'Übersicht neu starten', exact: true }).click(); const fresh = await restart;
  expect(fresh.status(), await fresh.text()).toBe(200); expect(new URL(fresh.url()).searchParams.has('tasks_after')).toBe(false); expect(new URL(fresh.url()).searchParams.has('as_of')).toBe(false);
  await expect(dashboard(page).getByRole('alert')).toHaveCount(0); await capture(page, testInfo, 'B2-native-cursor-restarted', hintPanel(page, familyLabels.tasks));
  await proof(testInfo, 'B2-native-empty-and-transport-faults', { emptyCounts: { units: empty.unit_count, tasks: empty.work_hints.tasks.total }, nativeReadStatusesBeforeLostDelivery: nativeStatuses, deliberateBindingChange: response.status(), restartedNativeURL: fresh.url() });
});
