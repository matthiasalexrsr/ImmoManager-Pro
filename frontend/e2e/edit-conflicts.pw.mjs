import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

for (const kind of ['properties', 'tenants', 'accounts']) {
  test(`${kind}: two real editors retain old revision and reconcile deliberately`, async ({ page, browser }, testInfo) => {
    test.setTimeout(120_000);
    await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
    await page.goto('/login');
    await page.getByLabel('Benutzername', { exact: true }).fill('demo');
    await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
    await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    const headers = { Authorization: `Bearer ${token}` };
    const post = async (path, data) => {
      const result = await page.request.post(`/api/v1${path}`, { headers, data });
      expect(result.ok(), await result.text()).toBeTruthy();
      return result.json();
    };
    const suffix = randomUUID().slice(0, 8);
    const name = `Parallel ${kind} ${suffix}`;
    const portfolio = await post('/portfolios', { name: `CAS ${suffix}` });
    const payload = kind === 'properties' ? { portfolio_id: portfolio.id, name, property_type: 'residential' }
      : kind === 'tenants' ? { full_name: name }
        : { portfolio_id: portfolio.id, name, account_type: 'Girokonto', currency: 'EUR' };
    const target = await post(`/${kind}`, payload);
    const other = await post(`/${kind}`, { ...payload, [kind === 'tenants' ? 'full_name' : 'name']: `${name} independently` });
    const path = `/api/v1/${kind}/${target.id}`;
    const contextB = await browser.newContext({ baseURL: process.env.IMMO_E2E_URL, storageState: await page.context().storageState() });
    try {
      const pageB = await contextB.newPage();
      const open = async activePage => {
        await activePage.goto(`/${kind}`);
        if (kind === 'properties') await activePage.getByRole('button', { name: `${name} bearbeiten`, exact: true }).click();
        else await activePage.getByRole('row').filter({ hasText: name }).filter({ hasNotText: 'independently' })
          .getByRole('button', { name: 'Bearbeiten', exact: true }).click();
      };
      await open(page);
      await open(pageB);
      const field = kind === 'properties' ? /^Objektname/ : kind === 'tenants' ? /^Vollständiger Name/ : /^Kontoname/;
      const dialogA = page.getByRole('dialog');
      const dialogB = pageB.getByRole('dialog');
      await dialogA.getByLabel(field).fill(`${name} A`);
      await dialogB.getByLabel(field).fill(`${name} B`);
      const savedA = page.waitForResponse(result => new URL(result.url()).pathname === path && result.request().method() === 'PUT');
      await dialogA.getByRole('button', { name: 'Speichern', exact: true }).click();
      expect((await savedA).status()).toBe(200);
      await expect(dialogA).not.toBeVisible();

      // A fresh server GET and an independent record mutation cannot renew B's
      // already-open form revision. The same-client cache case is also tested
      // directly in EditRevision.test.js without any mocked request helper.
      const latest = await pageB.request.get(path, { headers });
      expect((await latest.json())[kind === 'tenants' ? 'full_name' : 'name']).toBe(`${name} A`);
      const independent = await page.request.patch(`/api/v1/${kind}/${other.id}`, { headers: { ...headers,
        'If-Match': `"immo-v1:${kind}:${other.id}:${other.updated_at}"` },
        data: kind === 'tenants' ? { phone: '030123456' } : kind === 'properties' ? { city: 'Bonn' } : { bank_name: 'Independent Bank' } });
      expect(independent.status()).toBe(200);
      const staleWrite = pageB.waitForResponse(result => new URL(result.url()).pathname === path && result.request().method() === 'PUT');
      await dialogB.getByRole('button', { name: 'Speichern', exact: true }).click();
      const failed = await staleWrite;
      expect(failed.status()).toBe(412);
      expect(failed.request().headers()['if-match']).toContain(target.updated_at);
      await expect(dialogB.getByLabel(field)).toHaveValue(`${name} B`);
      await expect(dialogB.getByRole('region', { name: 'Änderungen abgleichen' })).toBeVisible();
      expect((await (await page.request.get(path, { headers })).json())[kind === 'tenants' ? 'full_name' : 'name']).toBe(`${name} A`);
      await dialogB.getByRole('button', { name: 'Aktuellen Stand prüfen', exact: true }).click();
      const reconcile = dialogB.getByRole('button', { name: 'Abgleich übernehmen', exact: true });
      await expect(reconcile).toBeDisabled();
      await dialogB.getByRole('combobox', { name: /^Wert für .+ auswählen$/ }).selectOption('draft');
      await reconcile.click();
      // Apply reconciliation only updates this draft, never the database.
      expect((await (await page.request.get(path, { headers })).json())[kind === 'tenants' ? 'full_name' : 'name']).toBe(`${name} A`);
      await expect(dialogB.getByLabel(field)).toHaveValue(`${name} B`);
      const savedB = pageB.waitForResponse(result => new URL(result.url()).pathname === path && result.request().method() === 'PUT');
      await dialogB.getByRole('button', { name: 'Speichern', exact: true }).click();
      expect((await savedB).status()).toBe(200);
      await expect(dialogB).not.toBeVisible();
      await pageB.reload();
      await expect(pageB.getByText(`${name} B`, { exact: true }).first()).toBeVisible();
      const verified = await (await page.request.get(path, { headers })).json();
      expect(verified[kind === 'tenants' ? 'full_name' : 'name']).toBe(`${name} B`);
      await testInfo.attach(`${kind}-persisted.json`, { body: Buffer.from(JSON.stringify({ original: target, verified })), contentType: 'application/json' });
    } finally { await contextB.close(); }
  });
}
