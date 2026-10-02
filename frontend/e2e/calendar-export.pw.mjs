import { randomUUID, createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

const passphrase = 'Synthetic Calendar Reader 2026';
async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}
async function create(page, headers, path, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBe(201); return response.json();
}
async function downloadCalendar(page, panel) {
  const pending = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'ICS herunterladen', exact: true }).click();
  const download = await pending;
  expect(download.suggestedFilename()).toBe('immomanager-calendar.ics');
  expect(await download.failure()).toBeNull();
  return readFile(await download.path());
}
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

test('explicit portfolio ICS: stable real snapshots, readonly scope and mobile controls', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const ownerHeaders = await login(page);
  const suffix = randomUUID();
  const left = await create(page, ownerHeaders, '/portfolios', { name: `Kalender Nord ${suffix}`, timezone: 'Europe/Berlin' });
  const right = await create(page, ownerHeaders, '/portfolios', { name: `Kalender Fremd ${suffix}`, timezone: 'Europe/London' });
  const property = await create(page, ownerHeaders, '/properties', { portfolio_id: left.id, name: `Terminobjekt ${suffix}`, property_type: 'residential' });
  const otherProperty = await create(page, ownerHeaders, '/properties', { portfolio_id: right.id, name: `Fremdobjekt ${suffix}`, property_type: 'residential' });
  const allDay = await create(page, ownerHeaders, '/calendar', { title: `Ganztägige Prüfung ${suffix}`, event_type: 'deadline', event_date: '2026-10-05', property_id: property.id });
  const timed = await create(page, ownerHeaders, '/calendar', { title: `Übergabe; Nord, Süd ${suffix}`, event_type: 'handover', event_date: '2026-10-06', event_time: '14:30', property_id: property.id,
    description: 'Originale Zeile\nWeitere Zeile', location: 'Haus Süd', participants: 'Synthetische Person; Beispiel' });
  await create(page, ownerHeaders, '/calendar', { title: `FREMDER TERMIN ${suffix}`, event_type: 'other', event_date: '2026-10-07', property_id: otherProperty.id });
  const username = `calendar-reader-${suffix}`;
  await create(page, ownerHeaders, '/auth/users', { username, email: `${username}@example.test`, full_name: 'Synthetic Calendar Reader', password: passphrase,
    role: 'readonly', portfolio_access: 'selected', portfolio_ids: [left.id] });

  const writes = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/calendar') && request.method() !== 'GET') writes.push(request.method());
  });
  await page.goto('/calendar');
  const panel = page.getByRole('region', { name: 'Kalender mitnehmen', exact: true });
  const select = panel.getByRole('combobox', { name: 'Portfolio für den Export', exact: true });
  await expect(select).toBeEnabled();
  await expect(panel.getByRole('button', { name: 'ICS herunterladen', exact: true })).toBeDisabled();
  await select.selectOption(left.id);
  const exported = await downloadCalendar(page, panel);
  const content = exported.toString('utf8').replace(/\r\n[ \t]/g, '');
  expect(content).toMatch(/^BEGIN:VCALENDAR\r\nVERSION:2.0\r\n/);
  expect(content).toMatch(/\r\nEND:VCALENDAR\r\n$/);
  expect(content.match(/BEGIN:VEVENT/g)).toHaveLength(2);
  expect(content).toContain(`UID:urn:uuid:${allDay.id}\r\n`);
  expect(content).toContain(`UID:urn:uuid:${timed.id}\r\n`);
  expect(content).toContain('DTSTART;VALUE=DATE:20261005\r\n');
  expect(content).toContain('DTSTART:20261006T123000Z\r\n');
  expect(content).toContain('X-IMMOMANAGER-SOURCE-TZID:Europe/Berlin\r\n');
  expect(content).toContain('DESCRIPTION:Originale Zeile\\nWeitere Zeile\r\n');
  expect(content).toContain('X-IMMOMANAGER-PARTICIPANTS:Synthetische Person\\; Beispiel\r\n');
  expect(content).not.toMatch(/FREMDER TERMIN|METHOD:|ATTENDEE[;:]|ORGANIZER[;:]/);
  expect(digest(await downloadCalendar(page, panel))).toBe(digest(exported));
  await expect(panel.getByRole('status')).toContainText(left.name);
  await testInfo.attach('synthetic-calendar.ics', { body: exported, contentType: 'text/calendar' });

  for (const width of [320, 360]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const control of [select, panel.getByRole('button', { name: 'ICS herunterladen', exact: true })]) {
      const box = await control.boundingBox(); expect(box).not.toBeNull();
      expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    await select.focus(); await page.keyboard.press('Tab');
    await expect(panel.getByRole('button', { name: 'ICS herunterladen', exact: true })).toBeFocused();
  }
  await testInfo.attach('calendar-export-360.png', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  expect(writes).toEqual([]);

  // The shared locale readiness helper verifies desktop header controls.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => localStorage.clear());
  const readerHeaders = await login(page, username, passphrase);
  await page.goto('/calendar');
  await expect(select).toBeEnabled();
  await expect(select.getByRole('option', { name: new RegExp(left.name) })).toHaveCount(1);
  await expect(select.getByRole('option', { name: new RegExp(right.name) })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Neu', exact: true })).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: allDay.title })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Operative Verarbeitung', exact: true })).toHaveCount(0);
  await select.selectOption(left.id);
  expect(digest(await downloadCalendar(page, panel))).toBe(digest(exported));
  for (const width of [320, 360]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(panel.getByRole('button', { name: 'ICS herunterladen', exact: true })).toBeVisible();
  }
  const foreign = await page.request.get(`/api/v1/calendar/export.ics?portfolio_id=${right.id}`, { headers: readerHeaders });
  expect(foreign.status()).toBe(404);
  expect((await page.request.get(`/api/v1/calendar/export.ics?portfolio_id=${left.id}`)).status()).toBe(401);
  const forbidden = await page.request.post('/api/v1/calendar', { headers: readerHeaders, data: { title: 'Forbidden reader write', event_type: 'other', event_date: '2026-10-08', property_id: property.id } });
  expect(forbidden.status()).toBe(403);
  const retained = await page.request.get('/api/v1/calendar', { headers: readerHeaders });
  expect(retained.status()).toBe(200); expect((await retained.json()).map(row => row.id).sort()).toEqual([allDay.id, timed.id].sort());
  expect(writes).toEqual([]);
});
