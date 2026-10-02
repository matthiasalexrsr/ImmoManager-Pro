import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const SEARCH = 'Vertrag, Immobilie, Einheit oder Mieter suchen';

async function login(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

async function create(page, path, headers, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function fixture(page, headers, tag, index, portfolio) {
  const suffix = String(index).padStart(3, '0');
  const property = await create(page, '/properties', headers, {
    portfolio_id: portfolio.id, name: `Workspace ${tag} property ${suffix}`, property_type: 'residential',
  });
  const unit = await create(page, '/units', headers, {
    property_id: property.id, label: `Workspace ${tag} unit ${suffix}`, unit_type: 'apartment', cold_rent: 672.34,
  });
  const tenant = await create(page, '/tenants', headers, { full_name: `Workspace ${tag} tenant ${suffix}` });
  const contract = await create(page, '/contracts', headers, {
    contract_number: `Workspace ${tag} ${suffix}`, property_id: property.id, unit_id: unit.id,
    tenant_id: tenant.id, start_date: '2026-01-01', status: 'draft',
  });
  return { property, unit, tenant, contract };
}

async function search(page, value) {
  await page.getByRole('searchbox', { name: SEARCH, exact: true }).fill(value);
  const response = page.waitForResponse(value => value.request().method() === 'GET'
    && new URL(value.url()).pathname === '/api/v1/contracts/workspace/page');
  await page.getByRole('button', { name: 'Filter anwenden', exact: true }).click();
  expect((await response).status()).toBe(200);
}

test('actual SQLite workspace reaches all pages and exact late references with a bounded visible export', async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const headers = await login(page);
  const tag = randomUUID();
  const portfolio = await create(page, '/portfolios', headers, { name: `Workspace ${tag}` });
  const boxes = [];
  // Only ordinary authenticated product APIs; the isolated runner owns all data.
  for (let index = 1; index <= 106; index += 1) boxes.push(await fixture(page, headers, tag, index, portfolio));
  const target = boxes.at(-1);
  const legacy = await page.request.get('/api/v1/contracts?limit=100&sort_by=contract_number&sort_order=asc', { headers });
  expect(legacy.status()).toBe(200);
  const cutoff = await legacy.json();
  expect(cutoff).toHaveLength(100);
  expect(cutoff.some(record => record.id === target.contract.id)).toBe(false);
  const requests = [];
  page.on('request', request => {
    if (request.method() === 'GET') requests.push(new URL(request.url()).pathname);
  });
  await page.goto('/contracts');
  await germanWorkspaceReady(page);
  await search(page, tag);
  const table = page.getByRole('table', { name: 'Verträge', exact: true });
  await expect(table.locator('tbody tr')).toHaveCount(25);
  const numbers = [];
  for (let index = 0; index < 5; index += 1) {
    const expected = boxes[index * 25].contract.contract_number;
    await expect(table.locator('tbody tr').first().locator('td').first()).toHaveText(expected);
    numbers.push(...await table.locator('tbody tr td:first-child').allTextContents());
    const next = page.getByRole('button', { name: 'Nächste Seite', exact: true });
    if (index < 4) {
      await expect(next).toBeEnabled();
      await next.click();
    } else await expect(next).toBeDisabled();
  }
  expect(numbers).toEqual(boxes.map(box => box.contract.contract_number));
  expect(new Set(numbers).size).toBe(106);
  await search(page, target.property.name);
  const row = table.getByRole('row').filter({ hasText: target.contract.contract_number });
  await expect(row).toContainText(target.property.name);
  await expect(row).toContainText(target.unit.label);
  await expect(row).toContainText(target.tenant.full_name);
  await expect(row).toContainText('672,34');
  expect(requests.filter(path => ['/api/v1/contracts', '/api/v1/properties', '/api/v1/units', '/api/v1/tenants'].includes(path))).toEqual([]);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Diese Seite als CSV', exact: true }).click();
  const csv = await readFile(await (await download).path(), 'utf8');
  expect(csv).toContain(target.contract.contract_number);
  expect(csv).not.toContain(boxes[0].contract.contract_number);
  await row.getByRole('button', { name: `Bearbeiten ${target.contract.contract_number}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Bearbeiten', exact: true });
  await expect(dialog.getByRole('combobox', { name: 'Immobilie *', exact: true })).toHaveValue(target.property.id);
  await expect(dialog.getByRole('combobox', { name: 'Einheit *', exact: true })).toHaveValue(target.unit.id);
  await expect(dialog.getByRole('combobox', { name: 'Mieter *', exact: true })).toHaveValue(target.tenant.id);
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect.poll(() => dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  }
  const screenshot = testInfo.outputPath('contract-workspace-editor-mobile.png');
  await page.screenshot({ path: screenshot });
  await testInfo.attach('contract-workspace-editor-mobile', { path: screenshot, contentType: 'image/png' });
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(row.getByRole('button', { name: `Bearbeiten ${target.contract.contract_number}`, exact: true })).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
});

test('actual workspace editor preserves stale ETag then saves only after explicit fresh reconciliation', async ({ page }) => {
  const headers = await login(page);
  const tag = randomUUID();
  const portfolio = await create(page, '/portfolios', headers, { name: `Workspace conflict ${tag}` });
  const box = await fixture(page, headers, tag, 1, portfolio);
  await page.goto('/contracts');
  await search(page, box.contract.contract_number);
  await page.getByRole('button', { name: `Bearbeiten ${box.contract.contract_number}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Bearbeiten', exact: true });
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  await dialog.getByLabel('Vertragsnummer *', { exact: true }).fill(`Reviewed local draft ${tag}`);
  const concurrent = await page.request.patch(`/api/v1/contracts/${box.contract.id}`, { headers,
    data: { notice_period: 'Synthetic server update preserved after reconciliation' } });
  expect(concurrent.status(), await concurrent.text()).toBe(200);
  const expectedFresh = concurrent.headers().etag;
  const saves = [];
  page.on('request', request => {
    if (request.method() === 'PUT' && new URL(request.url()).pathname === `/api/v1/contracts/${box.contract.id}`) {
      saves.push({ etag: request.headers()['if-match'], data: request.postDataJSON() });
    }
  });
  const rejected = page.waitForResponse(response => response.request().method() === 'PUT'
    && new URL(response.url()).pathname === `/api/v1/contracts/${box.contract.id}`);
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await rejected).status()).toBe(412);
  await expect(dialog.getByLabel('Vertragsnummer *', { exact: true })).toHaveValue(`Reviewed local draft ${tag}`);
  const stored = await page.request.get(`/api/v1/contracts/${box.contract.id}`, { headers });
  expect((await stored.json()).contract_number).toBe(box.contract.contract_number);
  await dialog.getByRole('button', { name: 'Aktuellen Stand prüfen', exact: true }).click();
  await dialog.getByRole('button', { name: 'Abgleich übernehmen', exact: true }).click();
  await expect(dialog.getByLabel('Kündigungsfrist', { exact: true })).toHaveValue('Synthetic server update preserved after reconciliation');
  const accepted = page.waitForResponse(response => response.request().method() === 'PUT'
    && new URL(response.url()).pathname === `/api/v1/contracts/${box.contract.id}`);
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await accepted).status()).toBe(200);
  await expect(dialog).toHaveCount(0);
  expect(saves).toHaveLength(2);
  expect(saves[0].etag).not.toBe(expectedFresh);
  expect(saves[1].etag).toBe(expectedFresh);
  const result = await page.request.get(`/api/v1/contracts/${box.contract.id}`, { headers });
  expect(await result.json()).toMatchObject({ contract_number: `Reviewed local draft ${tag}`,
    notice_period: 'Synthetic server update preserved after reconciliation' });
});
