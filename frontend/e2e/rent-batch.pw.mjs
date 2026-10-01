import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function read(page, path, headers) {
  const response = await page.request.get(`/api/v1${path}`, { headers });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function allCharges(page, headers) {
  const rows = [];
  for (let skip = 0; ; skip += 100) {
    const batch = await read(page, `/rent-charges?skip=${skip}&limit=100`, headers);
    rows.push(...batch);
    if (batch.length < 100) return rows;
  }
}

async function noOverflow(page) {
  // Resize updates responsive layout asynchronously; assert its settled result.
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
    { message: 'The workspace and modal must fit the viewport' }).toBeLessThanOrEqual(1);
}

test('saved rental generation: paused SQL preparation survives reload, then 132 months require explicit approval', async ({ page }, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  const headers = { Authorization: `Bearer ${token}` };
  const contracts = await read(page, '/contracts', headers);
  const contract = contracts.find(item => item.status === 'active' && !item.end_date);
  expect(contract, 'A genuine seeded open-ended lease is required').toBeTruthy();
  const before = await allCharges(page, headers);
  const startYear = Math.max(2046, Number(contract.start_date.slice(0, 4)) + 20);
  const startMonth = `${startYear}-01`;
  const endMonth = `${startYear + 10}-12`;
  const inRange = row => row.contract_id === contract.id && row.month >= startMonth && row.month <= endMonth;
  expect(before.filter(inRange)).toHaveLength(0);

  await page.goto('/rent-charges');
  await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: 'Monatliche Sollstellung', exact: true });
  await dialog.getByLabel('Ab Monat', { exact: false }).fill(startMonth);
  await dialog.getByLabel('Bis Monat', { exact: false }).fill(endMonth);
  await dialog.getByLabel('Verträge (optional)', { exact: true }).selectOption(contract.id);
  await dialog.getByRole('checkbox', { name: 'Als unterbrechbaren Lauf speichern', exact: true }).check();
  const createdResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rent-charges/batches'
    && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  let job = await created.json();
  expect(job).toMatchObject({ persistent: true, state: 'preparing', created_count: 0, parameters: {
    start_month: startMonth, end_month: endMonth, contract_ids: [contract.id],
  } });
  const base = `/rent-charges/batches/${job.id}`;

  // Use the real controls through their public API to stop at a deterministic
  // preparation boundary. No interception, synthetic response or fake clock.
  const advanced = await page.request.post(`/api/v1${base}/advance`, { headers, data: { cursor: job.cursor, budget: 1 } });
  expect(advanced.status()).toBe(200);
  job = await advanced.json();
  expect(job).toMatchObject({ state: 'preparing', contract_count: 1 });
  const paused = await page.request.post(`/api/v1${base}/pause`, { headers, data: { cursor: job.cursor } });
  expect(paused.status()).toBe(200);
  job = await paused.json();
  expect(job.state).toBe('paused');
  expect((await allCharges(page, headers)).filter(inRange)).toHaveLength(0);

  await page.reload();
  await germanWorkspaceReady(page);
  await page.getByRole('button', { name: 'Monatliche Sollstellung', exact: true }).click();
  await page.getByRole('button', { name: 'Gespeicherten Lauf öffnen', exact: true }).click();
  dialog = page.getByRole('dialog', { name: 'Gespeicherter Mietlauf', exact: true });
  await expect(dialog).toContainText(job.id);
  await expect(dialog).toContainText('Pausiert');
  await dialog.getByLabel('Einträge je Arbeitsschritt', { exact: true }).fill('25');
  await dialog.getByRole('button', { name: 'Lauf fortsetzen', exact: true }).click();
  const approve = dialog.getByRole('button', { name: 'Preisstand freigeben und erzeugen', exact: true });
  await expect(approve).toBeEnabled();
  const ready = await read(page, base, headers);
  expect(ready).toMatchObject({ persistent: true, state: 'ready', contract_count: 1, created_count: 0 });
  expect(ready.plan_hash).toMatch(/^[0-9a-f]{64}$/);
  expect(ready.sealed_at).toBeTruthy();
  const sealedPreview = await read(page, `${base}/preview?page_size=25`, headers);
  expect(sealedPreview.items).toHaveLength(25);
  expect(sealedPreview.has_more).toBe(true);
  expect(sealedPreview.items[0]).toMatchObject({ contract_id: contract.id, month: startMonth });
  await expect(dialog.getByRole('table')).toBeVisible();
  await expect(dialog).toContainText(contract.contract_number);
  await dialog.getByRole('button', { name: 'Nächste Seite', exact: true }).filter({ hasText: 'Nächste Seite' }).click();
  await expect(dialog).toContainText('Vorschauseite 2');
  const firstSecondPage = `${startYear + 2}-02`;
  await expect(dialog.getByRole('table')).toContainText(firstSecondPage);
  await dialog.getByRole('button', { name: 'Vorherige Seite', exact: true }).filter({ hasText: 'Vorherige Seite' }).click();
  await expect(dialog.getByRole('table')).toContainText(startMonth);
  expect((await allCharges(page, headers)).filter(inRange)).toHaveLength(0);

  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await noOverflow(page);
    await expect(approve).toBeEnabled();
    await expect(approve).toBeInViewport({ ratio: 1 });
    await testInfo.attach(`saved-rent-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  }
  await approve.click();
  await expect(dialog.getByRole('button', { name: 'Ergebnis übernehmen', exact: true })).toBeEnabled();
  const completed = await read(page, base, headers);
  expect(completed).toMatchObject({ state: 'done', created_count: 132, existing_count: 0, plan_hash: ready.plan_hash });
  const charges = (await allCharges(page, headers)).filter(inRange);
  expect(charges).toHaveLength(132);
  expect(new Set(charges.map(row => row.month)).size).toBe(132);
  expect(charges.every(row => Number(row.amount_paid) === 0 && row.status === 'open')).toBe(true);
  // Persisted charge rows expose the four accounting components, while the
  // sealed preview exposes their total; compare the real API contracts.
  const rentTotal = row => ['cold_rent', 'service_charge', 'heating_charge', 'other_charges']
    .reduce((total, key) => total + Number(row[key]), 0);
  for (const projected of sealedPreview.items) {
    const actual = charges.find(row => row.month === projected.month);
    expect(rentTotal(actual)).toBeCloseTo(Number(projected.total_amount), 2);
    expect(rentTotal(actual)).toBeGreaterThan(0);
  }
  await dialog.getByRole('button', { name: 'Ergebnis übernehmen', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  expect((await allCharges(page, headers)).filter(inRange)).toEqual(charges);
  const persisted = await read(page, base, headers);
  expect(persisted).toMatchObject({ state: 'done', created_count: 132, plan_hash: ready.plan_hash });
  await noOverflow(page);
});
