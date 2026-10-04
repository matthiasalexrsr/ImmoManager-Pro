import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect } from '@playwright/test';
import { germanWorkspaceReady } from './demoFixtures.mjs';

const password = 'Synthetic B2 Dashboard Passphrase 2026!';
export const dashboard = page => page.locator('.dashboard-home');
export const hintPanel = (page, title) => dashboard(page).getByRole('region', { name: title, exact: true });
export const pathIs = path => response => new URL(response.url()).pathname === `/api/v1${path}`;
export const addDays = (day, count) => new Date(Date.parse(`${day}T00:00:00Z`) + count * 86400000).toISOString().slice(0, 10);
export const familyLabels = { tasks: 'Offene Aufgaben', notifications: 'Benachrichtigungen', expiring_contracts: 'Vertragsenden in den nächsten 90 Tagen' };
export const cursorNames = { tasks: 'tasks_after', notifications: 'notifications_after', expiring_contracts: 'contracts_after' };
export function nativeApi(page, headers) {
  return async (path, data, method = data === undefined ? 'GET' : 'POST', expected = data === undefined ? 200 : 201) => {
    const response = await page.request.fetch(`/api/v1${path}`, { headers, method, ...(data === undefined ? {} : { data }) });
    expect(response.status(), `${method} ${path}: ${await response.text()}`).toBe(expected);
    return response.status() === 204 ? null : response.json();
  };
}
export async function login(page, account) {
  const response = await page.request.post('/api/v1/auth/login', { data: { username: account.username, password } });
  expect(response.status(), await response.text()).toBe(200); const preliminary = (await response.json()).access_token;
  const preferences = await page.request.put('/api/v1/auth/users/me/preferences', { headers: { Authorization: `Bearer ${preliminary}` }, data: { locale: 'de-DE', theme: 'light', sidebar_collapsed: false } });
  expect(preferences.status(), await preferences.text()).toBe(200);
  await page.goto('/login'); await page.getByLabel('Benutzername', { exact: true }).fill(account.username); await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  return nativeApi(page, headers);
}
export async function fixture(page, { units = 13, hints = 13, role = 'readonly', large = false } = {}) {
  const response = await page.request.post('/api/v1/auth/login', { data: { username: 'demo', password: 'Demo1234' } });
  expect(response.status(), await response.text()).toBe(200); const owner = nativeApi(page, { Authorization: `Bearer ${(await response.json()).access_token}` });
  expect(await (await page.request.get('/health')).json()).toMatchObject({ store_backend: 'SQLAlchemyStore', database_connected: true });
  const manifest = large ? JSON.parse(await readFile(process.env.IMMO_E2E_DASHBOARD_FIXTURE, 'utf8')) : null;
  if (manifest) expect(manifest.basis).toBe('native-owned-b2-synthetic-stock');
  const asOf = (await owner('/dashboard/stats?preview_limit=5')).as_of; const tag = manifest?.tag || randomUUID().slice(0, 8);
  const portfolio = manifest?.portfolio || await owner('/portfolios', { name: `B2 authorized ${tag}` });
  const account = await owner('/auth/users', { username: `b2-${tag}`, email: `b2-${tag}@example.test`, full_name: `B2 reader ${tag}`, password, role, portfolio_access: 'selected', portfolio_ids: [portfolio.id] });
  const expected = manifest?.expected || { total: units, occupied: 0, rented: 0, vacant: 0, reserved: 0, other: 0 };
  const unitRows = manifest?.unitRows || []; const tasks = []; const notifications = []; const contracts = [];
  if (!units && !hints) return { owner, account, portfolio, asOf, tag, expected, tasks, notifications, contracts };
  const property = manifest?.property || await owner('/properties', { portfolio_id: portfolio.id, name: `B2 property ${tag} ${'ObjectContext'.repeat(12)}`, property_type: 'residential' });
  const statuses = ['occupied', 'rented', 'vacant', 'reserved', 'maintenance'];
  for (let index = 0; index < (manifest ? 0 : units); index++) {
    const status = statuses[index % statuses.length]; const row = await owner('/units', { property_id: property.id, label: `B2 unit ${index} ${tag} ${'LongReference'.repeat(9)}`, unit_type: 'apartment', status });
    unitRows.push(row); if (['occupied', 'rented'].includes(status)) expected.occupied++;
    if (status === 'rented') expected.rented++; else if (['vacant', 'reserved'].includes(status)) expected[status]++; else if (status === 'maintenance') expected.other++;
  }
  for (let index = 0; index < hints; index++) {
    const unit = unitRows[index % unitRows.length];
    const task = await owner('/tasks', { title: `B2 task ${index} ${tag} ${index ? '' : 'TaskReference'.repeat(18)}`, due_date: index >= hints - 3 ? null : asOf, priority: index ? 'custom' : 'urgent', property_id: property.id, unit_id: unit.id }); tasks.push(task);
    notifications.push(await owner('/notifications', { title: `B2 notice ${index} ${tag}`, content: 'Synthetic dashboard fixture', notification_type: 'general', severity: 'info', entity_type: 'unit', entity_id: unit.id }));
    const tenant = await owner('/tenants', { full_name: `B2 tenant ${index} ${tag}` });
    contracts.push(await owner('/contracts', { contract_number: `B2 contract ${index} ${tag}`, property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, status: 'terminated', start_date: addDays(asOf, -365), end_date: addDays(asOf, index === 0 ? 0 : index === hints - 1 ? 90 : 30) }));
  }
  // A genuine unrelated portfolio is present in the same SQL database.
  const hidden = await owner('/portfolios', { name: `B2 hidden ${tag}` });
  const hiddenProperty = await owner('/properties', { portfolio_id: hidden.id, name: `B2 HIDDEN property ${tag}`, property_type: 'residential' });
  await owner('/units', { property_id: hiddenProperty.id, label: `B2 HIDDEN unit ${tag}`, unit_type: 'apartment', status: 'occupied' });
  await owner('/tasks', { title: `B2 HIDDEN task ${tag}`, due_date: asOf, property_id: hiddenProperty.id });
  tasks.sort((a, b) => (a.due_date === null) - (b.due_date === null) || (a.due_date || '').localeCompare(b.due_date || '') || Buffer.compare(Buffer.from(a.id), Buffer.from(b.id)));
  return { owner, account, portfolio, property, unitRows, lastUnit: manifest?.lastUnit, hidden, hiddenProperty, asOf, tag, expected, tasks, notifications, contracts };
}
export async function capture(page, testInfo, name, target = dashboard(page)) {
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const full = testInfo.outputPath(`${name}-${width}.png`); await page.screenshot({ path: full, fullPage: true, animations: 'disabled' }); await testInfo.attach(`${name}-${width}`, { path: full, contentType: 'image/png' });
    await target.scrollIntoViewIfNeeded(); const detail = testInfo.outputPath(`${name}-${width}-detail.png`); await page.screenshot({ path: detail, animations: 'disabled' }); await testInfo.attach(`${name}-${width}-detail`, { path: detail, contentType: 'image/png' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}
export async function proof(testInfo, name, value) { await testInfo.attach(name, { body: Buffer.from(JSON.stringify(value, null, 2)), contentType: 'application/json' }); }
