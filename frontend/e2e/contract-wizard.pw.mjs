import { test, expect } from './demoFixtures.mjs';

async function loginOwner(page) {
  const response = await page.request.post('/api/v1/auth/login', {
    data: { username: 'demo', password: 'Demo1234' },
  });
  expect(response.status()).toBe(200);
  const tokens = await response.json();
  await page.goto('/login');
  await page.evaluate(({ access_token, refresh_token }) => {
    localStorage.setItem('access_token', access_token);
    localStorage.setItem('refresh_token', refresh_token);
    localStorage.setItem('locale', 'de-DE');
  }, tokens);
  return { Authorization: `Bearer ${tokens.access_token}` };
}

async function listCount(page, path, headers) {
  const response = await page.request.get(path, { headers });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  expect(Array.isArray(body)).toBe(true);
  return body.length;
}

test('contract wizard escapes user markup and never persists bank details', async ({ page }) => {
  test.setTimeout(120_000);
  await loginOwner(page);
  const legacyIban = 'DE44500105175407324931';
  await page.evaluate(value => {
    localStorage.setItem('mietvertragWizardFormState_v2', JSON.stringify({
      fields: { 'zahlung-iban': { type: 'text', value } },
    }));
  }, legacyIban);
  let releaseAsset;
  const assetReady = new Promise(resolve => { releaseAsset = resolve; });
  await page.route('**/mietvertrag/static/mietvertrag_wizard/vendor/pdfmake.min.js', async route => {
    await assetReady;
    await route.continue();
  });
  await page.goto('/contract-wizard');
  await page.getByRole('button', { name: 'Vollständigen Klausel-/Staffel-Assistenten öffnen', exact: true }).click();

  const iframe = page.locator('iframe');
  await expect(iframe).toBeVisible();
  const frame = page.frameLocator('iframe');
  try {
    await expect(frame.getByRole('status')).toHaveText('Vertragsassistent wird vorbereitet …');
    await expect(frame.getByText('Schritt 1: Angaben zum Vermieter')).not.toBeVisible();
  } finally {
    releaseAsset();
  }
  await expect(frame.getByText('Schritt 1: Angaben zum Vermieter')).toBeVisible();
  const migrated = await page.evaluate(() => ({
    current: localStorage.getItem('mietvertragWizardFormState_v3'),
    legacy: localStorage.getItem('mietvertragWizardFormState_v2'),
  }));
  expect(migrated.legacy).toBeNull();
  expect(migrated.current).not.toContain(legacyIban);
  await expect(frame.locator('#zahlung-iban')).toHaveValue('');

  const untrustedName = '<em data-wizard-injected="landlord">Untrusted landlord</em>';
  await frame.locator('input[name="vermieter-name"]').fill(untrustedName);
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await frame.locator('input[name="mieter-name"]').fill('Sicherer Mieter');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await frame.locator('#objekt-strasse').fill('Teststraße 1');
  await frame.locator('#objekt-plz').fill('60311');
  await frame.locator('#objekt-ort').fill('Frankfurt');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await frame.locator('#mietbeginn').fill('01112026');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await frame.locator('#miete-grund').fill('800.00');
  await frame.locator('#miete-grund').blur();
  await expect(frame.locator('#miete-grund')).toHaveValue('800,00');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  const landlordIban = 'DE02120300000000202051';
  const tenantIban = 'DE12500105170648489890';
  await frame.locator('#zahlung-iban').fill(landlordIban);
  await frame.locator('#zahlung-bic').fill('BYLADEM1001');
  await frame.locator('#mandat-inhaber').fill('Sicherer Mieter');
  await frame.locator('#mandat-iban').fill(tenantIban);
  await frame.locator('#mandat-bic').fill('INGDDEFFXXX');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  const untrustedAgreement = '<em data-wizard-injected="agreement">Untrusted agreement</em>';
  await frame.locator('#sonstige-vereinbarungen').fill(untrustedAgreement);
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await expect(frame.locator('#vertragstext')).toContainText(untrustedName);
  await expect(frame.locator('#vertragstext')).toContainText(untrustedAgreement);
  await expect(frame.locator('#vertragstext em[data-wizard-injected]')).toHaveCount(0);

  page.once('dialog', dialog => dialog.accept());
  await frame.getByRole('button', { name: 'Im Browser speichern', exact: true }).click();

  const persisted = await page.evaluate(() => ({
    current: localStorage.getItem('mietvertragWizardFormState_v3'),
    legacy: localStorage.getItem('mietvertragWizardFormState_v2'),
  }));
  expect(persisted.legacy).toBeNull();
  expect(persisted.current).toContain('Sicherer Mieter');
  expect(persisted.current).not.toContain(landlordIban);
  expect(persisted.current).not.toContain(tenantIban);
  expect(persisted.current).not.toContain('BYLADEM1001');
  expect(persisted.current).not.toContain('INGDDEFFXXX');

  const downloadPromise = page.waitForEvent('download');
  await frame.getByRole('button', { name: 'PDF herunterladen', exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mietvertrag.pdf');

  await page.route('**/api/v1/contract-wizard/pdf', route => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Grundmiete fehlt.' }),
  }));
  let fallbackDownload = false;
  const markDownload = () => { fallbackDownload = true; };
  page.on('download', markDownload);
  const validationDialogPromise = page.waitForEvent('dialog').then(async dialog => {
    const message = dialog.message();
    await dialog.accept();
    return message;
  });
  await frame.getByRole('button', { name: 'PDF herunterladen', exact: true }).click();
  expect(await validationDialogPromise).toContain('Grundmiete fehlt.');
  await page.waitForTimeout(300);
  page.off('download', markDownload);
  expect(fallbackDownload).toBe(false);
});

test('legacy wizard blocks incoherent fixed-term and Staffel drafts before preview', async ({ page }) => {
  test.setTimeout(120_000);
  await loginOwner(page);
  await page.goto('/contract-wizard');
  await page.getByRole('button', { name: 'Vollständigen Klausel-/Staffel-Assistenten öffnen', exact: true }).click();
  const frame = page.frameLocator('iframe');
  await expect(frame.getByText('Schritt 1: Angaben zum Vermieter')).toBeVisible();

  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 1: Angaben zum Vermieter')).toBeVisible();
  expect(await frame.locator('input[name="vermieter-name"]').evaluate(el => el.validationMessage)).toContain('Vermieter');
  await frame.locator('input[name="vermieter-name"]').fill('Validierungsvermieter');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await frame.locator('input[name="mieter-name"]').fill('Validierungsmieter');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await frame.locator('#objekt-strasse').fill('Prüfstraße 7');
  await frame.locator('#objekt-plz').fill('60311');
  await frame.locator('#objekt-ort').fill('Frankfurt');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await frame.locator('#mietzeit-art').selectOption('befristet');
  await frame.locator('#mietbeginn').fill('01112026');
  await frame.locator('#mietende').fill('31102027');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 4: Mietzeit')).toBeVisible();
  expect(await frame.locator('#befristet-grund-option').evaluate(el => el.validationMessage)).toContain('Befristungsgrund');
  await frame.locator('#befristet-grund-option').selectOption('Eigenbedarf');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();

  await frame.getByLabel('Expertenmodus anzeigen (zusätzliche Optionen)').check();
  const rent = frame.locator('#miete-grund');
  await rent.fill('12345678901234567890,99');
  await rent.blur();
  await expect(rent).toHaveValue('12.345.678.901.234.567.890,99');
  await rent.fill('800,001');
  await rent.blur();
  await expect(rent).toHaveValue('800,001');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 5: Miete und Nebenkosten')).toBeVisible();
  expect(await rent.evaluate(el => el.validationMessage)).toContain('centgenau');
  await rent.fill('800,00');
  await rent.blur();
  await expect(rent).toHaveValue('800,00');
  await frame.locator('#mieterhoehung').selectOption('staffel');
  await frame.locator('.staffel-row').first().locator('.staffel-betrag').fill('850,00');
  await frame.locator('.staffel-row').first().locator('.staffel-ab').fill('12');
  await frame.locator('#add-staffel').click();
  const second = frame.locator('.staffel-row').nth(1);
  await second.locator('.staffel-betrag').fill('900,001');
  await second.locator('.staffel-betrag').blur();
  await expect(second.locator('.staffel-betrag')).toHaveValue('900,001');
  await second.locator('.staffel-ab').fill('24');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 5: Miete und Nebenkosten')).toBeVisible();
  expect(await second.locator('.staffel-betrag').evaluate(el => el.validationMessage)).toContain('centgenau');
  await second.locator('.staffel-betrag').fill('900');
  await second.locator('.staffel-betrag').blur();
  await expect(second.locator('.staffel-betrag')).toHaveValue('900,00');
  await second.locator('.staffel-ab').fill('12');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 5: Miete und Nebenkosten')).toBeVisible();
  expect(await second.locator('.staffel-ab').evaluate(el => el.validationMessage)).toContain('aufsteigend');
  await second.locator('.staffel-ab').fill('24');
  await frame.getByRole('button', { name: 'Weiter', exact: true }).click();
  await expect(frame.getByText('Schritt 6: Zahlung & SEPA')).toBeVisible();
});

test('persisted contract wizard reviews, publishes and records manual signature without cash side effects', async ({ page }) => {
  test.setTimeout(120_000);
  const headers = await loginOwner(page);
  const before = {
    contracts: await listCount(page, '/api/v1/contracts', headers),
    deposits: await listCount(page, '/api/v1/deposits', headers),
    bookings: await listCount(page, '/api/v1/bookings', headers),
  };

  await page.goto('/contract-wizard');
  await page.getByRole('button', { name: 'Neuen Entwurf vorbereiten', exact: true }).click();
  const property = page.getByLabel('Immobilie *', { exact: true });
  await expect.poll(() => property.locator('option').count()).toBeGreaterThan(1);
  await property.selectOption({ index: 1 });
  const unit = page.getByLabel('Einheit *', { exact: true });
  await expect.poll(() => unit.locator('option').count()).toBeGreaterThan(1);
  await unit.selectOption({ index: 1 });

  const contractNumber = `E2E-WIZ-${Date.now()}`;
  await page.getByLabel('Vermieter / vollständiger Name *', { exact: true }).fill('E2E Vermieter');
  await page.getByLabel('Vermieteranschrift *', { exact: true }).fill('Teststraße 10, 60311 Frankfurt');
  await page.getByLabel('Mieter / vollständiger Name *', { exact: true }).fill('E2E Mieter');
  await page.getByLabel('Vertragsnummer *', { exact: true }).fill(contractNumber);
  await page.getByLabel('Vereinbarte Kaution', { exact: true }).fill('1234.56');
  await page.getByLabel('Eigene Vereinbarungen / vollständiger Text', { exact: true })
    .fill('Eigene vollständig geprüfte E2E-Vereinbarungen.');
  await expect(page.getByText(/Es entstehen keine Zahlungseingänge/)).toBeVisible();

  const savedResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/contract-wizard/drafts'
      && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Entwurf speichern', exact: true }).click();
  const savedHttp = await savedResponse;
  expect(savedHttp.status(), await savedHttp.text()).toBe(201);
  const saved = await savedHttp.json();
  await expect(page).toHaveURL(new RegExp(`[?&]draft=${saved.id}`));

  const reviewedResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/v1/contract-wizard/drafts/${saved.id}/review`
      && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Gespeicherten Stand prüfen', exact: true }).click();
  expect((await reviewedResponse).status()).toBe(200);
  await expect(page.getByRole('heading', { name: '4 · Prüfstand und Vorschau', exact: true })).toBeVisible();

  const previewDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Geprüfte PDF-Vorschau herunterladen', exact: true }).click();
  expect((await previewDownload).suggestedFilename()).toBe('mietvertrag-vorschau.pdf');
  const publishedResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/v1/contract-wizard/drafts/${saved.id}/publish`
      && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Geprüften Vertrag bestätigen & anlegen', exact: true }).click();
  const confirmPublish = page.getByRole('alertdialog');
  await expect(confirmPublish).toContainText('Es wird keine Zahlung gebucht.');
  await confirmPublish.getByRole('button', { name: 'Bestätigen', exact: true }).click();
  const publishedHttp = await publishedResponse;
  expect(publishedHttp.status(), await publishedHttp.text()).toBe(200);
  const published = await publishedHttp.json();
  expect(published).toMatchObject({ state: 'committed', id: saved.id });
  expect(published.contract_id).toBeTruthy();
  expect(published.document_id).toBeTruthy();
  await expect(page.getByRole('heading', { name: 'Vertrag und Belege angelegt', exact: true })).toBeVisible();

  const finalDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Unveränderliches Vertrags-PDF herunterladen', exact: true }).click();
  expect((await finalDownload).suggestedFilename()).toBe('mietvertrag.pdf');

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Vertrag und Belege angelegt', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Manuelle Unterzeichnung erfassen', exact: true }).click();
  await page.getByLabel('Nachvollziehbare Belegreferenz', { exact: true }).fill('Papieroriginal E2E-Ordner 7');
  const signatureResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/v1/contract-wizard/drafts/${saved.id}/signatures`
      && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Unterzeichnungsbeleg bestätigen', exact: true }).click();
  const confirmSignature = page.getByRole('alertdialog');
  await expect(confirmSignature).toContainText('Der Vertragsstatus wird dadurch nicht aktiviert.');
  await confirmSignature.getByRole('button', { name: 'Bestätigen', exact: true }).click();
  expect((await signatureResponse).status()).toBe(200);

  await page.reload();
  await expect(page.locator('.contract-result')).toContainText('Papieroriginal E2E-Ordner 7');
  await expect(page.getByRole('button', { name: 'Manuelle Unterzeichnung erfassen', exact: true })).toHaveCount(0);

  const after = {
    contracts: await listCount(page, '/api/v1/contracts', headers),
    deposits: await listCount(page, '/api/v1/deposits', headers),
    bookings: await listCount(page, '/api/v1/bookings', headers),
  };
  expect(after.contracts).toBe(before.contracts + 1);
  expect(after.deposits).toBe(before.deposits);
  expect(after.bookings).toBe(before.bookings);
});
