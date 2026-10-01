import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('bookings: server pages, complete filtered CSV, bounded references and persistent CAS edit', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
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
  const accounts = await api('/accounts');
  expect(accounts.length).toBeGreaterThan(0);
  const prefix = `BrowserLedger ${randomUUID().slice(0, 8)}`;
  const created = [];
  for (let index = 0; index < 64; index += 1) {
    created.push(await api('/bookings', { account_id: accounts[0].id, booking_date: '2046-10-01',
      amount: index % 2 ? 12.34 : -12.34, status: 'open',
      payment_text: index === 0 ? `=SUM(2,3) ${prefix}` : `${prefix} row ${index}` }));
  }
  const ledgerRequests = [];
  page.on('request', request => {
    if (request.method() === 'GET' && new URL(request.url()).pathname.startsWith('/api/v1/bookings')) ledgerRequests.push(request.url());
  });
  await page.goto('/bookings');
  await expect(page.getByRole('heading', { name: 'Buchungen', exact: true })).toBeVisible();
  const search = page.getByRole('searchbox', { name: 'Buchungstext oder ID suchen', exact: true });
  await search.fill(prefix);
  await search.press('Enter');
  const table = page.getByRole('table');
  await expect(table.locator('tbody tr')).toHaveCount(25);
  await expect(table).toContainText(prefix);
  const firstPage = await api(`/bookings/page?page_size=25&search=${encodeURIComponent(prefix)}`);
  const expectedFirst = firstPage.items.map(row => row.payment_text);
  const visibleTexts = () => table.locator('tbody tr td:nth-child(5)').allTextContents();
  expect(await visibleTexts()).toEqual(expectedFirst);
  await page.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(page.getByText('Seite 2', { exact: true })).toBeVisible();
  const secondPage = await api(`/bookings/page?page_size=25&search=${encodeURIComponent(prefix)}&cursor=${encodeURIComponent(firstPage.next_cursor)}`);
  await expect.poll(visibleTexts).toEqual(secondPage.items.map(row => row.payment_text));
  expect(secondPage.items.some(row => firstPage.items.some(first => first.id === row.id))).toBe(false);
  await page.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(14);
  await expect(page.getByRole('button', { name: 'Weiter', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Zurück', exact: true }).click();
  await expect.poll(visibleTexts).toEqual(secondPage.items.map(row => row.payment_text));

  // CSV uses every match, independent of the currently displayed page.
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'CSV herunterladen', exact: true }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe('bookings.csv');
  const text = (await readFile(await download.path(), 'utf8')).replace(/^\uFEFF/, '');
  expect(text.trimEnd().split('\r\n')).toHaveLength(65);
  for (const booking of created) expect(text).toContain(booking.id);
  expect(text).toContain(`'=SUM(2,3) ${prefix}`);

  // Exercise the browser's real filesystem WritableStream. Substitute only
  // the interactive chooser with an isolated OPFS file; HTTP/SQL stay real.
  await page.evaluate(async () => {
    const directory = await navigator.storage.getDirectory();
    window.bookingStreamFile = await directory.getFileHandle('booking-stream-acceptance.csv', { create: true });
    window.showSaveFilePicker = async () => window.bookingStreamFile;
  });
  const streamingRequest = page.waitForRequest(request => new URL(request.url()).pathname === '/api/v1/bookings/export.csv');
  await page.getByRole('button', { name: 'CSV direkt speichern', exact: true }).click();
  const streamRequest = await streamingRequest;
  expect(streamRequest.headers().authorization).toMatch(/^Bearer /);
  expect(streamRequest.url()).not.toContain('access_token');
  await expect(page.getByText('CSV-Export fertig.', { exact: true })).toBeVisible();
  const streamedText = await page.evaluate(async () => (await window.bookingStreamFile.getFile()).text());
  expect(streamedText.replace(/^\uFEFF/, '')).toBe(text);

  const selected = secondPage.items[0];
  await page.getByRole('button', { name: `Buchung bearbeiten ${selected.payment_text}`, exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue(selected.account_id);
  const writes = [];
  page.on('request', request => { if (request.method() === 'PUT' || request.method() === 'POST') writes.push(request); });
  await dialog.getByRole('searchbox', { name: 'Konto suchen', exact: true }).fill(accounts[0].name);
  await dialog.getByRole('searchbox', { name: 'Konto suchen', exact: true }).press('Enter');
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(0);
  const replacement = `${prefix} edited persistently`;
  await dialog.getByLabel('Buchungstext', { exact: true }).fill(replacement);
  const edited = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/bookings/${selected.id}` && response.request().method() === 'PUT');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const editResponse = await edited;
  expect(editResponse.status()).toBe(200);
  expect(editResponse.request().headers()['if-match']).toContain(`immo-v1:bookings:${selected.id}:`);
  await expect(dialog).not.toBeVisible();
  expect((await api(`/bookings/${selected.id}`)).payment_text).toBe(replacement);
  await page.reload();
  await search.fill(replacement); await search.press('Enter');
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(table).toContainText(replacement);
  await expect(table).toContainText(accounts[0].name);

  expect(ledgerRequests.some(url => new URL(url).pathname === '/api/v1/bookings')).toBe(false);
  expect(ledgerRequests.filter(url => new URL(url).pathname.includes('/lookup/')).every(url => new URL(url).searchParams.get('page_size') === '25')).toBe(true);
  const desktop = testInfo.outputPath('bookings-desktop.png');
  await page.screenshot({ path: desktop, fullPage: true });
  await testInfo.attach('Buchungsseite Desktop', { path: desktop, contentType: 'image/png' });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await expect(page.getByRole('button', { name: 'Filter anwenden', exact: true })).toBeVisible();
    const screenshot = testInfo.outputPath(`bookings-mobile-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await testInfo.attach(`Buchungsseite ${width}px`, { path: screenshot, contentType: 'image/png' });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: `Buchung bearbeiten ${replacement}`, exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('combobox', { name: 'Konto *', exact: true })).toHaveValue(selected.account_id);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const editorScreenshot = testInfo.outputPath('bookings-editor-mobile.png');
  await page.screenshot({ path: editorScreenshot, fullPage: true });
  await testInfo.attach('Buchungseditor mobil', { path: editorScreenshot, contentType: 'image/png' });
  await dialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
});
