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
  }, tokens);
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
