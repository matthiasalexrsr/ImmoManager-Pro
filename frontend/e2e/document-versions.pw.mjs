import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');

async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

test('explicit document originals survive version upload, lost response, restore and fresh scoped logins', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  const ownerHeaders = await login(page);
  const unique = randomUUID();
  async function create(path, data) {
    const response = await page.request.post('/api/v1' + path, { headers: ownerHeaders, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  }
  const portfolio = await create('/portfolios', { name: `Version scope ${unique}` });
  const foreign = await create('/portfolios', { name: `Foreign version scope ${unique}` });
  const property = await create('/properties', { portfolio_id: portfolio.id, name: `Version property ${unique}`, property_type: 'residential' });
  const unit = await create('/units', { property_id: property.id, label: 'Version A', unit_type: 'apartment' });
  const title = `Synthetic ${unique} ${'LongImmutableTitle'.repeat(10)}`;
  const original = Buffer.from('Synthetic original bytes: äöüß € — source must remain unchanged.\n'.repeat(400));
  const next = Buffer.from('Synthetic deliberately different reviewed revision.\n'.repeat(500));
  const originalName = `SyntheticOriginal_${'LongFilename'.repeat(9)}.txt`;
  await page.goto('/documents');
  const uploadedResponse = page.waitForResponse(response => response.url().includes('/files/upload?') && response.request().method() === 'POST');
  await page.locator('.photo-drop-zone input[type=file]').setInputFiles({ name: originalName, mimeType: 'text/plain', buffer: original });
  const uploaded = await uploadedResponse;
  expect(uploaded.status(), await uploaded.text()).toBe(200);
  const originalUrl = (await uploaded.json()).file_url;
  await page.getByRole('button', { name: 'Dokument erstellen', exact: true }).click();
  const metadata = page.getByRole('dialog', { name: 'Dokument erstellen', exact: true });
  await metadata.getByLabel('Titel *', { exact: true }).fill(title);
  await metadata.getByRole('searchbox', { name: 'Immobilie suchen', exact: true }).fill(property.name);
  await metadata.getByRole('button', { name: property.name, exact: true }).click();
  await metadata.getByRole('searchbox', { name: 'Einheit suchen', exact: true }).fill(unit.label);
  await metadata.getByRole('button', { name: unit.label, exact: true }).click();
  await metadata.getByLabel('Tags', { exact: true }).fill('synthetic, immutable-evidence');
  const createdResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/documents' && response.request().method() === 'POST');
  await metadata.getByRole('button', { name: 'Speichern', exact: true }).click();
  const created = await createdResponse;
  expect(created.status(), await created.text()).toBe(201);
  const document = await created.json();
  expect(document).toMatchObject({ title, file_url: originalUrl, property_id: property.id, unit_id: unit.id });
  await expect(metadata).not.toBeVisible();
  // Keep the still-visible upload receipt in this mounted page. Reloading first
  // would silently erase a mobile overflow in the transient source URL status.
  await expect(page.locator('.photo-drop-zone')).toContainText(originalUrl);
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect(page.locator('.photo-drop-zone')).toContainText(originalUrl);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('searchbox', { name: 'Dokumente durchsuchen' }).fill(title);
  await page.getByRole('button', { name: `${title} Versionshistorie`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dokumentversionen', exact: true });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Dateiansicht', exact: true })).toHaveCount(0);
  await expect(dialog.getByText('Original noch nicht archiviert', { exact: true })).toBeVisible();
  await dialog.getByLabel('Kommentar zum Vorgang', { exact: true }).fill('Explicitly reviewed original capture');
  await expect(dialog.getByRole('button', { name: 'Original archivieren', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Original und Prüfsumme prüfen', exact: true }).click();
  await expect(dialog.getByText(`SHA256 ${hash(original)}`, { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Original archivieren', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(dialog.getByText('Fassung 1 ist gespeichert.', { exact: true })).toBeVisible();

  // A real committed upload response is deliberately lost. The user must keep
  // their draft and explicitly retry the same command, never create a second row.
  const uploadPath = `/api/v1/documents/${document.id}/versions`;
  let accepted;
  const commandReferences = new Set();
  await page.route('**' + uploadPath, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const result = await route.fetch();
    expect(result.status(), await result.text()).toBe(201);
    accepted = await result.json();
    commandReferences.add(accepted.id);
    await route.abort('failed');
  });
  const nextFile = { name: 'SyntheticReviewedNewVersion.txt', mimeType: 'text/plain', buffer: next };
  await dialog.getByLabel('Kommentar zum Vorgang', { exact: true }).fill('Reviewed revision with retained retry reference');
  await dialog.getByLabel('Datei für neue Fassung', { exact: true }).setInputFiles(nextFile);
  await dialog.getByRole('button', { name: 'Neue Fassung veröffentlichen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  expect(accepted.number).toBe(2);
  expect(commandReferences.size).toBe(1);
  await expect(dialog.getByLabel('Kommentar zum Vorgang', { exact: true })).toHaveValue('Reviewed revision with retained retry reference');
  await expect(dialog.getByLabel('Datei für neue Fassung', { exact: true })).not.toBeEmpty();
  await page.unroute('**' + uploadPath);
  await dialog.getByRole('button', { name: 'Neue Fassung veröffentlichen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(dialog.getByText('Fassung 2 ist gespeichert.', { exact: true })).toBeVisible();
  await expect(dialog.locator('.document-version-list > li')).toHaveCount(2);
  let history = await (await page.request.get(uploadPath, { headers: ownerHeaders })).json();
  expect(history.items.map(row => row.number)).toEqual([2, 1]);
  expect(history.head).toMatchObject({ id: accepted.id, sha256: hash(next), predecessor_id: history.items[1].id });

  await dialog.getByLabel('Kommentar zum Vorgang', { exact: true }).fill('Explicit restore of the reviewed original bytes');
  await dialog.getByRole('button', { name: 'Als neue Fassung wiederherstellen', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect(dialog.getByText('Fassung 3 ist gespeichert.', { exact: true })).toBeVisible();
  await expect(dialog.locator('.document-version-list > li')).toHaveCount(3);
  history = await (await page.request.get(uploadPath, { headers: ownerHeaders })).json();
  expect(history.items.map(row => row.number)).toEqual([3, 2, 1]);
  expect(history.head).toMatchObject({ operation: 'restore', sha256: hash(original),
    predecessor_id: accepted.id, restored_from_id: history.items[2].id });
  expect((await (await page.request.get(`/api/v1/documents/${document.id}`, { headers: ownerHeaders })).json()).file_url).toBe(originalUrl);
  expect(await (await page.request.get(originalUrl, { headers: ownerHeaders })).body()).toEqual(original);
  for (const [index, expected] of [[0, original], [1, next], [2, original]]) {
    const download = page.waitForEvent('download');
    await dialog.locator('.document-version-list > li').nth(index).getByRole('button', { name: 'Archivierte Datei herunterladen', exact: true }).click();
    expect(await readFile(await (await download).path())).toEqual(expected);
  }
  // Exercise both the overlay and its underlying page while the original upload
  // receipt remains mounted. A new login/reload must not conceal this state.
  const opener = page.getByRole('button', { name: `${title} Versionshistorie`, exact: true });
  for (const width of [360, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(dialog.locator('.document-version-list > li')).toHaveCount(3);
    await expect(page.locator('.photo-drop-zone')).toContainText(originalUrl);
    await expect.poll(() => page.evaluate(() => ({ width: innerWidth, pageWidth: document.documentElement.scrollWidth,
      dialogFits: [...document.querySelectorAll('.document-version-history, .document-version-history button')]
        .every(element => { const bounds = element.getBoundingClientRect(); return bounds.left >= -1 && bounds.right <= innerWidth + 1 && element.scrollWidth <= element.clientWidth + 1; }),
    }))).toEqual({ width, pageWidth: width, dialogFits: true });
    const close = dialog.getByRole('button', { name: 'Schließen', exact: true });
    await close.focus();
    await page.keyboard.press('Shift+Tab');
    await expect(dialog.getByLabel('Fassung 1 vergleichen', { exact: true })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(close).toBeFocused();
    if (width === 320) {
      const screenshot = testInfo.outputPath('immutable-document-history-mobile.png');
      await page.screenshot({ path: screenshot });
      await testInfo.attach('immutable-document-history-mobile', { path: screenshot, contentType: 'image/png' });
    }
    await close.click();
    await expect(opener).toBeFocused();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect(page.locator('.photo-drop-zone')).toContainText(originalUrl);
    if (width === 360) await opener.click();
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  const password = 'Synthetic Document Reader Passphrase 2026';
  const reader = `versions-reader-${unique}`;
  const outsider = `versions-foreign-${unique}`;
  await create('/auth/users', { username: reader, email: `${reader}@example.com`, full_name: 'Synthetic scoped readonly reader', password,
    role: 'readonly', portfolio_access: 'selected', portfolio_ids: [portfolio.id] });
  await create('/auth/users', { username: outsider, email: `${outsider}@example.com`, full_name: 'Synthetic foreign manager', password,
    role: 'verwalter', portfolio_access: 'selected', portfolio_ids: [foreign.id] });
  await page.evaluate(() => localStorage.clear());
  const readerHeaders = await login(page, reader, password);
  await page.goto('/documents');
  await page.getByRole('searchbox', { name: 'Dokumente durchsuchen' }).fill(title);
  await page.getByRole('button', { name: `${title} Versionshistorie`, exact: true }).click();
  await expect(dialog.locator('.document-version-list > li')).toHaveCount(3);
  await expect(dialog.getByLabel('Kommentar zum Vorgang', { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Neue Fassung veröffentlichen', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Als neue Fassung wiederherstellen', exact: true })).toHaveCount(0);
  const readerDownload = page.waitForEvent('download');
  await dialog.locator('.document-version-list > li').first().getByRole('button', { name: 'Archivierte Datei herunterladen', exact: true }).click();
  expect(hash(await readFile(await (await readerDownload).path()))).toBe(hash(original));
  expect((await page.request.post(uploadPath + '/restore', { headers: readerHeaders, data: {
    idempotency_key: `readonly-${unique}`, expected_document_etag: history.document_etag, expected_head_id: history.head.id,
    source_version_id: history.items[2].id, comment: 'Synthetic forbidden write', confirmed: true,
  } })).status()).toBe(403);
  await page.evaluate(() => localStorage.clear());
  const outsiderHeaders = await login(page, outsider, password);
  await page.goto('/documents');
  await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(0);
  expect((await page.request.get(uploadPath, { headers: outsiderHeaders })).status()).toBe(404);
  const frozenPath = `${uploadPath}/${history.head.id}/download`;
  expect((await page.request.get(frozenPath, { headers: outsiderHeaders })).status()).toBe(404);
  expect((await page.request.get(frozenPath)).status()).toBe(401);
  expect((await (await page.request.get(uploadPath, { headers: ownerHeaders })).json()).items).toHaveLength(3);

});
