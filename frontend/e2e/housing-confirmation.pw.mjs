import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

test('housing confirmation: explicit move-in, lost response, immutable correction and private PDF', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
  const create = async (path, data) => {
    const response = await page.request.post(`/api/v1${path}`, { headers, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  };
  const unique = randomUUID();
  const portfolio = await create('/portfolios', { name: `Housing ${unique}` });
  const property = await create('/properties', { name: `Housing property ${unique}`, property_type: 'residential',
    portfolio_id: portfolio.id, address_line: 'Prüfstraße 17', postal_code: '64646', city: 'Heppenheim' });
  const unit = await create('/units', { property_id: property.id, label: 'Wohnung im Obergeschoss', unit_type: 'apartment' });
  const tenant = await create('/tenants', { full_name: 'Synthetische Mieterin Élodie Müller' });
  const contract = await create('/contracts', { contract_number: `Housing-${unique}`, property_id: property.id,
    unit_id: unit.id, tenant_id: tenant.id, start_date: '2026-01-01', status: 'active' });
  const rootPath = `/api/v1/contracts/${contract.id}/housing-confirmations`;
  const records = async () => {
    const response = await page.request.get(rootPath, { headers });
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()).items;
  };
  await page.goto('/contracts');
  await germanWorkspaceReady(page);
  await page.getByRole('searchbox', { name: 'Vertrag, Immobilie, Einheit oder Mieter suchen', exact: true }).fill(contract.contract_number);
  await page.getByRole('button', { name: 'Filter anwenden', exact: true }).click();
  await page.getByRole('row').filter({ hasText: contract.contract_number }).getByRole('button', { name: 'Ablauf prüfen', exact: true }).click();
  await page.getByRole('dialog', { name: 'Verlängerung oder Kündigung', exact: true })
    .getByRole('button', { name: 'Wohnungsgeberbestätigung', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Wohnungsgeberbestätigung', exact: true });
  await expect(dialog.getByLabel('Tatsächlicher Einzug', { exact: true })).toHaveValue('');
  await dialog.getByLabel('Tatsächlicher Einzug', { exact: true }).fill('2026-01-15');
  await dialog.getByLabel('Anschrift der Wohnung', { exact: true }).fill('Prüfstraße 17\n64646 Heppenheim');
  await dialog.getByLabel('Wohnungsbezeichnung', { exact: true }).fill('Obergeschoss, links');
  await dialog.getByLabel('Name des Wohnungsgebers', { exact: true }).fill('Synthetische Verwaltung GmbH');
  await dialog.getByLabel('Anschrift des Wohnungsgebers', { exact: true }).fill('Verwaltungsstraße 3\n64646 Heppenheim');
  await dialog.getByRole('combobox', { name: 'Eigentumsverhältnis', exact: true }).selectOption('same');
  await dialog.getByLabel('Ausstellungsdatum', { exact: true }).fill('2026-01-16');
  await dialog.getByLabel('Ausstellende Person', { exact: true }).fill('Synthetischer Verwalter Jörg');
  await dialog.getByRole('combobox', { name: 'Rolle der ausstellenden Person', exact: true }).selectOption('authorized_person');
  await dialog.getByLabel('Vollständiger Name 1', { exact: true }).fill('Synthetische Mieterin Élodie Müller');
  for (let index = 2; index <= 45; index += 1) {
    await dialog.getByRole('button', { name: 'Person hinzufügen', exact: true }).click();
    await dialog.getByLabel(`Vollständiger Name ${index}`, { exact: true }).fill(`Synthetische einziehende Person ${index} mit einem ausgesprochen langen Familiennamen`);
  }
  const review = async () => {
    await dialog.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
    await expect(dialog.getByText('45 Personen in dieser Vorschau', { exact: true })).toBeVisible();
    for (const label of [
      'Ich bestätige, dass die eingetragenen Personen tatsächlich in die Wohnung einziehen.',
      'Ich bestätige, dass die ausstellende Person zur Ausstellung dieser Bestätigung befugt ist.',
      'Ich bestätige, dass das angegebene Einzugsdatum der tatsächliche Einzug ist.',
    ]) await dialog.getByRole('checkbox', { name: label, exact: true }).check();
  };
  await review();
  const previewPopup = page.waitForEvent('popup');
  await dialog.getByRole('button', { name: 'PDF-Vorschau öffnen', exact: true }).click();
  const previewTab = await previewPopup;
  await expect(previewTab).toHaveURL(/^blob:/);
  await expect(dialog.getByRole('alert')).toHaveCount(0);
  expect(await records()).toHaveLength(0);
  await previewTab.close();
  let lost = false;
  let originalCommand;
  await page.route(`**${rootPath}`, async route => {
    if (route.request().method() === 'POST' && !lost) {
      originalCommand = route.request().postDataJSON();
      const response = await route.fetch();
      expect(response.status(), await response.text()).toBe(201);
      lost = true;
      await route.abort('failed');
    } else await route.continue();
  });
  await dialog.getByRole('button', { name: 'Freigeben und Original speichern', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Unverändert erneut senden', exact: true })).toBeVisible();
  expect(await records()).toHaveLength(1);
  const retry = page.waitForRequest(request => new URL(request.url()).pathname === rootPath && request.method() === 'POST');
  await dialog.getByRole('button', { name: 'Unverändert erneut senden', exact: true }).click();
  expect((await retry).postDataJSON()).toEqual(originalCommand);
  await expect(dialog.getByText('Die freigegebene Fassung wurde als unveränderliches Original gespeichert.', { exact: true })).toBeVisible();
  const first = (await records())[0];
  expect(await records()).toHaveLength(1);
  const pdf = await page.request.get(`${rootPath}/${first.document_id}/download`, { headers });
  expect(pdf.status(), await pdf.text()).toBe(200);
  const originalBytes = await pdf.body();
  expect(originalBytes.subarray(0, 5).toString()).toBe('%PDF-');
  const anonymous = await page.request.get(`${rootPath}/${first.document_id}/download`);
  expect(anonymous.status()).toBe(401);
  const popup = page.waitForEvent('popup');
  await dialog.getByRole('button', { name: 'PDF öffnen', exact: true }).click();
  const pdfTab = await popup;
  await expect(pdfTab).toHaveURL(/^blob:/);
  await expect(dialog.getByRole('alert')).toHaveCount(0);
  await pdfTab.close();
  await dialog.getByRole('button', { name: 'Korrektur erstellen', exact: true }).click();
  await dialog.getByLabel('Tatsächlicher Einzug', { exact: true }).fill('2026-01-17');
  await review();
  await dialog.getByRole('button', { name: 'Freigeben und Original speichern', exact: true }).click();
  await expect(dialog.getByText('Die freigegebene Fassung wurde als unveränderliches Original gespeichert.', { exact: true })).toBeVisible();
  const revised = await records();
  expect(revised).toHaveLength(2);
  expect(revised.find(row => row.document_id !== first.document_id).correction_of).toEqual({ document_id: first.document_id, version_id: first.version_id });
  expect((await page.request.get(`${rootPath}/${first.document_id}/download`, { headers }).then(response => response.body()))).toEqual(originalBytes);
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const size = await dialog.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      return { width: element.clientWidth, scroll: element.scrollWidth,
        overflowing: [...element.querySelectorAll('*')].filter(child => child.getBoundingClientRect().right > bounds.right + 1)
          .map(child => ({ tag: child.tagName, className: child.className, text: child.textContent?.slice(0, 80) })).slice(0, 8) };
    });
    expect(size.scroll, JSON.stringify(size.overflowing)).toBeLessThanOrEqual(size.width + 1);
    await page.screenshot({ path: testInfo.outputPath(`housing-${width}.png`), fullPage: true });
  }
  await dialog.getByRole('button', { name: 'Schließen', exact: true }).last().click();
  await expect(dialog).toHaveCount(0);
});
