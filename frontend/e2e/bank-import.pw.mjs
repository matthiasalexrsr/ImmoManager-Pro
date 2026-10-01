import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function workspace(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const api = async (path, data) => {
    const response = data === undefined ? await page.request.get(`/api/v1${path}`, { headers })
      : await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
  };
  const prefix = `BankImport ${randomUUID().slice(0, 8)}`;
  const bankAccountDigits = String(BigInt(`0x${randomUUID().replaceAll('-', '')}`) % 10_000_000_000n).padStart(10, '0');
  const bankBody = `37040044${bankAccountDigits}`;
  const checksum = String(98n - BigInt(`${bankBody}131400`) % 97n).padStart(2, '0');
  const portfolios = await api('/portfolios');
  const account = await api('/accounts', { portfolio_id: portfolios[0].id, name: prefix,
    account_type: 'bank', iban: `DE${checksum}${bankBody}` });
  await page.goto('/bookings');
  await expect(page.getByRole('heading', { name: 'Buchungen', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Bankdatei importieren', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Bankdatei importieren', exact: true });
  await panel.getByRole('searchbox', { name: 'Zielkonto suchen', exact: true }).fill(prefix);
  await panel.getByRole('searchbox', { name: 'Zielkonto suchen', exact: true }).press('Enter');
  await expect(panel.getByRole('option', { name: prefix, exact: true })).toBeAttached();
  await panel.getByRole('combobox', { name: 'Zielkonto', exact: true }).selectOption(account.id);
  return { panel, account, api, prefix };
}

async function checkFile(page, panel, name, bytes) {
  await panel.getByLabel('Bankdatei', { exact: true }).setInputFiles({ name,
    mimeType: name.endsWith('.csv') ? 'text/csv' : 'application/octet-stream', buffer: Buffer.from(bytes) });
  const received = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/bookings/imports'
    && response.request().method() === 'POST');
  await panel.getByRole('button', { name: 'Datei prüfen und Vorschau speichern', exact: true }).click();
  const response = await received;
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function approve(page, panel) {
  await expect(panel.getByRole('button', { name: 'Geprüfte Buchungen verbindlich importieren', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: 'Geprüfte Buchungen verbindlich importieren', exact: true }).click();
  const confirmation = page.getByRole('alertdialog');
  await expect(confirmation).toContainText('Alle geprüften Buchungen jetzt gemeinsam veröffentlichen?');
  const received = page.waitForResponse(response => /\/api\/v1\/bookings\/imports\/[^/]+\/confirm$/.test(new URL(response.url()).pathname));
  await confirmation.getByRole('button', { name: 'Bestätigen', exact: true }).click();
  const response = await received;
  expect(response.status(), await response.text()).toBe(200);
  await expect(confirmation).not.toBeVisible();
  return response.json();
}

test('bank CSV: stored errors, exact preview, explicit atomic approval, history and file replay', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const { panel, account, api, prefix } = await workspace(page);
  const writes = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/bookings\/imports\/[^/]+\/confirm$/.test(new URL(request.url()).pathname)) writes.push(request);
  });
  const invalid = await checkFile(page, panel, 'invalid.csv', `date;amount;text\n2046-10-01;1.001;${prefix}\n`);
  expect(invalid.state).toBe('invalid');
  await expect(panel.getByText('Keine Buchung wurde veröffentlicht.', { exact: false })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Geprüfte Buchungen verbindlich importieren', exact: true })).toHaveCount(0);
  expect((await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items).toHaveLength(0);
  expect(writes).toHaveLength(0);

  await panel.getByRole('combobox', { name: 'Datumsformat', exact: true }).selectOption('%d.%m.%Y');
  await panel.getByRole('combobox', { name: 'Dezimaltrennzeichen', exact: true }).selectOption(',');
  const source = `date;amount;text\n01.10.2046;0,10;${prefix} same\n01.10.2046;0,10;${prefix} same\n02.10.2046;-1,23;${prefix} expense\n`;
  const job = await checkFile(page, panel, 'reviewed.csv', source);
  expect(job.state).toBe('ready');
  const preview = panel.getByRole('region', { name: 'Geprüfte Vorschau', exact: true });
  await expect(preview.getByRole('row')).toHaveCount(4);
  expect((await api(`/bookings/imports/${job.id}/preview`)).items.map(row => row.amount_cents)).toEqual([10, 10, -123]);
  expect((await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items).toHaveLength(0);
  await panel.getByRole('button', { name: 'Geprüfte Buchungen verbindlich importieren', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Geprüfte Buchungen verbindlich importieren', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(0);
  const committed = await approve(page, panel);
  expect(committed.published_count).toBe(3);
  await expect(panel.getByText('Veröffentlichte Buchungen: 3', { exact: true })).toBeVisible();
  const bookings = (await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items;
  expect(bookings).toHaveLength(3);
  expect(bookings.filter(row => row.payment_text === `${prefix} same`)).toHaveLength(2);
  expect(bookings.every(row => row.status === 'open' && Number(row.allocated_amount) === 0)).toBe(true);
  expect((await api(`/bookings/imports/${job.id}/receipts`)).items.map(row => row.booking_id).sort()).toEqual(bookings.map(row => row.id).sort());

  await page.reload();
  await page.getByRole('button', { name: 'Bankdatei importieren', exact: true }).click();
  await panel.getByRole('searchbox', { name: 'Zielkonto suchen', exact: true }).fill(prefix);
  await expect(panel.getByRole('option', { name: prefix, exact: true })).toBeAttached();
  await panel.getByRole('combobox', { name: 'Zielkonto', exact: true }).selectOption(account.id);
  await panel.getByText('Gespeicherte Importe dieses Kontos', { exact: true }).click();
  await panel.getByRole('button', { name: /reviewed.csv · Verbindlich importiert/ }).click();
  await expect(panel.getByText('Veröffentlichte Buchungen: 3', { exact: true })).toBeVisible();
  await panel.getByRole('combobox', { name: 'Datumsformat', exact: true }).selectOption('%d.%m.%Y');
  await panel.getByRole('combobox', { name: 'Dezimaltrennzeichen', exact: true }).selectOption(',');
  const replay = await checkFile(page, panel, 'reviewed.csv', source);
  expect(replay.id).toBe(job.id); expect(replay.replay).toBe(true);
  await expect(panel.getByText('Veröffentlichte Buchungen: 3', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect((await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items).toHaveLength(3);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width > 400 ? 1000 : 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) {
      const outside = await page.evaluate(() =>
        [...document.querySelectorAll('main *')].filter(element => element.getBoundingClientRect().right > innerWidth)
          .slice(0, 20).map(element => ({ tag: element.tagName, class: element.className, right: element.getBoundingClientRect().right })));
      await testInfo.attach(`overflow-${width}`, { contentType: 'application/json', body: Buffer.from(JSON.stringify(outside)) });
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`bank-import-${width}.png`);
    await panel.screenshot({ path: screenshot });
    await testInfo.attach(`Bankimport ${width}px`, { path: screenshot, contentType: 'image/png' });
  }
});

test('bank MT940: complete balance and each physical row remain distinct before explicit publication', async ({ page }) => {
  test.setTimeout(120_000);
  const { panel, account, api, prefix } = await workspace(page);
  await panel.getByRole('combobox', { name: 'Dateiformat', exact: true }).selectOption('mt940');
  const source = `:20:${prefix}\n:25:${account.iban}\n:28C:1/1\n:60F:C261001EUR0,00\n:61:2610011001C1,01NTRFNONREF\n:86:Same\n:61:2610011001C1,01NTRFNONREF\n:86:Same\n:61:2610011001D0,02NTRFNONREF\n:86:Expense\n:62F:C261001EUR2,00\n`;
  const job = await checkFile(page, panel, 'statement.sta', source);
  expect(job.state).toBe('ready'); expect(job.row_count).toBe(3);
  await expect(panel.getByRole('region', { name: 'Geprüfte Vorschau', exact: true }).getByRole('row')).toHaveCount(4);
  expect((await api(`/bookings/imports/${job.id}/preview`)).items.map(row => row.amount_cents)).toEqual([101, 101, -2]);
  expect((await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items).toHaveLength(0);
  expect((await approve(page, panel)).published_count).toBe(3);
  expect((await api(`/bookings/page?account_id=${account.id}&page_size=25`)).items).toHaveLength(3);
});
