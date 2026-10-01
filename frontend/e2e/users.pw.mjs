import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const passphrase = 'Browser Users Passphrase 2026';
const owner = { username: 'demo', password: 'Demo1234' };
const unique = prefix => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

async function login(page, account, success = true) {
  await page.goto('/login');
  await page.evaluate(() => { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.setItem('locale', 'de-DE'); });
  await page.reload();
  await page.getByLabel('Benutzername', { exact: true }).fill(account.username);
  await page.getByLabel('Passwort', { exact: true }).fill(account.password);
  const completed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/login' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  const response = await completed;
  expect(response.status()).toBe(success ? 200 : 401);
  if (success) { await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page); }
  else { await expect(page.getByRole('alert')).toBeVisible(); await expect(page).toHaveURL(/\/login$/); }
}

async function headers(page) { return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` }; }
async function createFixture(page, role, prefix) {
  const username = unique(prefix);
  const response = await page.request.post('/api/v1/auth/users', { headers: await headers(page), data: { username, email: `${username}@example.com`, full_name: username, password: passphrase, role } });
  expect(response.status(), await response.text()).toBe(201);
  return { ...(await response.json()), password: passphrase };
}
async function management(page) {
  await page.goto('/settings');
  await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  const section = page.getByRole('region', { name: 'Benutzerverwaltung', exact: true });
  await expect(section.getByRole('table')).toBeVisible();
  return section;
}
async function edit(page, section, name) {
  await section.getByRole('button', { name: `${name} bearbeiten`, exact: true }).click();
  return page.getByRole('dialog');
}
async function savePatch(page, dialog, id, changes) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/auth/users/${id}` && response.request().method() === 'PATCH');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  expect(response.request().postDataJSON()).toEqual(changes);
  const result = await response.json();
  await expect(dialog).not.toBeVisible();
  return result;
}

test('owner: create account, persist changed fields and role, deactivate, reactivate and sign in', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await login(page, owner);
  const section = await management(page);
  // Personal account role and activation have no editable controls.
  const me = await (await page.request.get('/api/v1/auth/me', { headers: await headers(page) })).json();
  const ownDialog = await edit(page, section, me.full_name);
  await expect(ownDialog.getByRole('combobox')).toHaveCount(0);
  await ownDialog.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  await section.getByRole('button', { name: 'Benutzer anlegen', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const username = unique('ui-created');
  const name = `UI Benutzer ${username}`;
  await dialog.getByLabel(/^Benutzername/).fill(username);
  await dialog.getByLabel(/^Vollständiger Name/).fill(name);
  await dialog.getByLabel(/^E-Mail-Adresse/).fill(`${username}@example.com`);
  await dialog.getByLabel(/^Startpassphrase/).fill(passphrase);
  await expect(dialog.getByLabel(/^Rolle/)).toHaveValue('readonly');
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/users' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  const response = await pending; expect(response.status(), await response.text()).toBe(201);
  const account = await response.json();
  expect(account).toMatchObject({ username, full_name: name, role: 'readonly', is_active: true });
  expect(account).not.toHaveProperty('hashed_password'); expect(account).not.toHaveProperty('totp_secret');
  await expect(dialog).not.toBeVisible();
  await expect(section.getByRole('table')).not.toContainText(passphrase);
  await page.reload();
  await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  const updatedName = `${name} gespeichert`;
  const updatedEmail = `${username}-updated@example.com`;
  const changes = { full_name: updatedName, email: updatedEmail, role: 'verwalter' };
  const editDialog = await edit(page, section, name);
  await editDialog.getByLabel(/^Vollständiger Name/).fill(updatedName);
  await editDialog.getByLabel(/^E-Mail-Adresse/).fill(updatedEmail);
  await editDialog.getByLabel(/^Rolle/).selectOption('verwalter');
  expect(await savePatch(page, editDialog, account.id, changes)).toMatchObject(changes);
  await page.reload(); await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  const row = section.getByRole('row').filter({ hasText: updatedEmail });
  await expect(row).toContainText(updatedName); await expect(row).toContainText('Verwalter');
  const deactivate = await edit(page, section, updatedName);
  await deactivate.getByLabel(/^Kontostatus/).selectOption('inactive');
  expect(await savePatch(page, deactivate, account.id, { is_active: false })).toMatchObject({ is_active: false });
  await login(page, { username, password: passphrase }, false);
  await login(page, owner);
  await management(page);
  const activate = await edit(page, section, updatedName);
  await activate.getByLabel(/^Kontostatus/).selectOption('active');
  expect(await savePatch(page, activate, account.id, { is_active: true })).toMatchObject({ is_active: true });
  // Real persisted account credentials, not an injected token, must work after activation.
  await login(page, { username, password: passphrase });
  await management(page);
  const profile = await (await page.request.get('/api/v1/auth/me', { headers: await headers(page) })).json();
  expect(profile).toMatchObject({ id: account.id, full_name: updatedName, email: updatedEmail, role: 'verwalter', is_active: true });
  await expect(section.getByRole('button', { name: 'Benutzer anlegen', exact: true })).toHaveCount(0);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const screenshot = testInfo.outputPath(`users-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`users-${width}`, { path: screenshot, contentType: 'image/png' });
  }
  expect(errors).toEqual([]);
});

test('manager: protect owners and own activation, edit non-owner contacts and toggle access', async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, owner);
  const manager = await createFixture(page, 'verwalter', 'ui-manager');
  const target = await createFixture(page, 'readonly', 'ui-target');
  const protectedOwner = await createFixture(page, 'eigentuemer', 'ui-owner');
  await login(page, manager);
  const section = await management(page);
  await expect(section.getByRole('button', { name: 'Benutzer anlegen', exact: true })).toHaveCount(0);
  const ownerRow = section.getByRole('row').filter({ hasText: protectedOwner.email });
  await expect(ownerRow.getByRole('button')).toHaveCount(0);
  const self = await edit(page, section, manager.full_name);
  await expect(self.getByRole('combobox')).toHaveCount(0);
  await self.getByRole('button', { name: 'Abbrechen', exact: true }).click();
  const dialog = await edit(page, section, target.full_name);
  await expect(dialog.getByLabel(/^Rolle/)).toHaveCount(0);
  const changes = { full_name: `${target.full_name} aktualisiert`, email: `${target.username}-new@example.com`, is_active: false };
  await dialog.getByLabel(/^Vollständiger Name/).fill(changes.full_name);
  await dialog.getByLabel(/^E-Mail-Adresse/).fill(changes.email);
  await dialog.getByLabel(/^Kontostatus/).selectOption('inactive');
  expect(await savePatch(page, dialog, target.id, changes)).toMatchObject(changes);
  await page.reload(); await page.getByRole('button', { name: 'Benutzer', exact: true }).click();
  await expect(section.getByRole('row').filter({ hasText: changes.email })).toContainText('Deaktiviert');
  const managerHeaders = await headers(page);
  expect((await page.request.patch(`/api/v1/auth/users/${protectedOwner.id}`, { headers: managerHeaders, data: { full_name: 'Verboten' } })).status()).toBe(403);
  expect((await page.request.patch(`/api/v1/auth/users/${target.id}`, { headers: managerHeaders, data: { role: 'eigentuemer' } })).status()).toBe(403);
  expect((await page.request.post('/api/v1/auth/login', { data: { username: target.username, password: target.password } })).status()).toBe(401);
  const activate = await edit(page, section, changes.full_name);
  await activate.getByLabel(/^Kontostatus/).selectOption('active');
  await savePatch(page, activate, target.id, { is_active: true });
  await login(page, target);
  const me = await (await page.request.get('/api/v1/auth/me', { headers: await headers(page) })).json();
  expect(me).toMatchObject({ id: target.id, full_name: changes.full_name, email: changes.email, is_active: true, role: 'readonly' });
});

test('read-only: settings have no user tab or management/version requests', async ({ page }) => {
  await login(page, owner);
  const reader = await createFixture(page, 'readonly', 'ui-readonly');
  await login(page, reader);
  const protectedRequests = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/auth/users' || path === '/api/v1/admin/version') protectedRequests.push(path);
  });
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Einstellungen', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Benutzer', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Benutzerverwaltung', exact: true })).toHaveCount(0);
  expect((await page.request.get('/api/v1/auth/users', { headers: await headers(page) })).status()).toBe(403);
  expect(protectedRequests).toEqual([]);
});
