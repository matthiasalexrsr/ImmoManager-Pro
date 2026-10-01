import { readFile } from 'node:fs/promises';
import { test as base, expect } from '@playwright/test';

// Real browser events, downloads and SQL-backed endpoints. No intercepted API.
const test = base.extend({
  page: async ({ page }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
    await use(page);
    expect(errors, 'The browser must not emit uncaught JavaScript errors').toEqual([]);
  },
});

async function get(page, path, headers) {
  const response = await page.request.get(`/api/v1${path}`, { headers });
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

async function previewOneUnbookedMonth(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const contracts = await get(page, '/contracts', headers);
  const before = await get(page, '/rent-charges', headers);
  const contract = contracts.find(item => item.status === 'active' && !item.end_date);
  expect(contract, 'The real seed provides an active, open-ended lease').toBeTruthy();
  const monthDate = new Date(`${contract.start_date.slice(0, 7)}-01T12:00:00Z`);
  let month;
  for (let offset = 0; offset < 120; offset += 1) {
    const candidate = monthDate.toISOString().slice(0, 7);
    if (!before.some(item => item.contract_id === contract.id && item.month === candidate)) {
      month = candidate;
      break;
    }
    monthDate.setUTCMonth(monthDate.getUTCMonth() + 1);
  }
  expect(month, 'An unbooked contractual month is required').toBeTruthy();

  const generationRequests = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/rent-charges/generate') {
      generationRequests.push(request.postDataJSON());
    }
  });
  await page.goto('/rent-charges');
  await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Monatliche Sollstellung', exact: true });
  await dialog.getByLabel('Ab Monat', { exact: false }).fill(month);
  await dialog.getByLabel('Bis Monat', { exact: false }).fill(month);
  await dialog.getByLabel('Verträge (optional)', { exact: true }).selectOption(contract.id);
  const previewResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rent-charges/preview'
    && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  const response = await previewResponse;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  expect(preview.candidates).toHaveLength(1);
  expect(preview.candidates[0]).toMatchObject({ contract_id: contract.id, month });
  const row = dialog.getByRole('row').filter({ hasText: contract.contract_number }).filter({ hasText: month });
  await expect(row).toHaveCount(1);
  const commit = dialog.getByRole('button', { name: 'Sollstellungen buchen', exact: true });
  await expect(commit).toBeEnabled();
  return { headers, before, contract, month, dialog, commit, preview, generationRequests };
}

for (const interaction of ['search Enter', 'column selection', 'CSV download']) {
  test(`monthly rent preview: ${interaction} does not book charges`, async ({ page }, testInfo) => {
    const state = await previewOneUnbookedMonth(page);
    const { headers, before, contract, month, dialog, commit, preview, generationRequests } = state;
    const expectUnbooked = async () => {
      // Reading the actual database also detects a completed accidental submit.
      const current = await get(page, '/rent-charges', headers);
      expect(generationRequests, 'Preview interaction must never submit the generation endpoint').toHaveLength(0);
      expect(current).toEqual(before);
      await expect(dialog).toBeVisible();
      await expect(commit).toBeEnabled();
    };

    if (interaction === 'search Enter') {
      const search = dialog.getByRole('searchbox').or(dialog.getByRole('textbox'));
      await search.fill(contract.contract_number);
      await search.press('Enter');
    } else if (interaction === 'column selection') {
      await dialog.getByRole('button', { name: 'Spalten anpassen', exact: true }).click();
      await expectUnbooked();
      const checkbox = dialog.getByRole('checkbox', { name: 'Teilmonat', exact: true });
      await checkbox.uncheck();
      await expect(dialog.getByRole('columnheader', { name: /Teilmonat/ })).toHaveCount(0);
      await expectUnbooked();
      await checkbox.check();
      await expect(dialog.getByRole('columnheader', { name: /Teilmonat/ })).toBeVisible();
      // An outside click dismisses the column popup while keeping the form open.
      await dialog.getByRole('heading', { name: 'Monatliche Sollstellung', exact: true }).click();
    } else {
      const downloadPromise = page.waitForEvent('download');
      await dialog.getByRole('button', { name: 'CSV', exact: true }).click();
      const download = await downloadPromise;
      expect(await download.failure()).toBeNull();
      expect(download.suggestedFilename()).toMatch(/\.csv$/);
      const csv = await readFile(await download.path(), 'utf8');
      expect(csv).toContain(contract.contract_number);
      expect(csv).toContain(month);
      await testInfo.attach('preview-export', { body: csv, contentType: 'text/csv' });
    }

    await expectUnbooked();

    const generatedResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rent-charges/generate'
      && response.request().method() === 'POST');
    // Activating the named commit button is the explicit intent to book.
    await commit.click();
    const generated = await generatedResponse;
    expect(generated.status()).toBe(200);
    expect(await generated.json()).toMatchObject({ created_count: 1, skipped_count: 0 });
    expect(generationRequests).toEqual([{
      start_month: month, end_month: month, contract_ids: [contract.id], preview_hash: preview.preview_hash,
    }]);
    await expect(dialog).not.toBeVisible();
    await page.reload();
    const persisted = (await get(page, '/rent-charges', headers))
      .filter(item => item.contract_id === contract.id && item.month === month);
    expect(persisted).toHaveLength(1);
    expect(Number(persisted[0].amount_paid)).toBe(0);
    expect(['cold_rent', 'service_charge', 'heating_charge', 'other_charges']
      .reduce((sum, key) => sum + Number(persisted[0][key] || 0), 0)).toBeCloseTo(Number(preview.total_amount), 2);
    // The seeded charge list is paginated; filter rather than assuming row order.
    const main = page.getByRole('main');
    await main.getByRole('textbox', { name: 'Suchen Sollstellungen', exact: true }).fill(contract.contract_number);
    await expect(page.getByRole('row').filter({ hasText: contract.contract_number }).filter({ hasText: month })).toHaveCount(1);
  });
}
