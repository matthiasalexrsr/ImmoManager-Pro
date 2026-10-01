import { randomUUID } from 'node:crypto';
import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

async function api(page, headers, path, data) {
  const response = await page.request.fetch(`/api/v1${path}`, { headers, method: data === undefined ? 'GET' : 'POST', data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function run(page, day) {
  await page.getByRole('button', { name: 'Operativen Lauf ausführen', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Operativen Lauf ausführen', exact: true });
  await dialog.getByLabel(/^Stichtag/).fill(day);
  await dialog.getByLabel(/^Nachholzeitraum/).fill('366');
  const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/tasks/operational-tick' && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Operativen Lauf ausführen', exact: true }).click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  await expect(dialog).not.toBeVisible();
  return response.json();
}

test('operational task tick: month end, explicit completion and repeat survive real reload', async ({ page }, testInfo) => {
  const headers = await login(page);
  const title = `Browser Monatskontrolle ${randomUUID().slice(0, 8)}`;
  const original = await api(page, headers, '/tasks', { title, due_date: '2026-01-31', recurrence_rule: 'FREQ=MONTHLY;COUNT=2' });
  await page.goto('/tasks');
  await expect(page.getByText('Automatische Verarbeitung ist deaktiviert. Ein manueller Lauf ist möglich.', { exact: true })).toBeVisible();
  await run(page, '2026-02-28');
  const children = (await api(page, headers, '/tasks?limit=1000')).filter(task => task.parent_task_id === original.id);
  expect(children).toHaveLength(1);
  expect(children[0].due_date).toBe('2026-02-28');
  const row = page.getByRole('row').filter({ hasText: title }).filter({ hasText: '28.2.2026' });
  await row.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  const edit = page.getByRole('dialog');
  await edit.getByLabel(/^Status/).selectOption('completed');
  await edit.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(edit).not.toBeVisible();
  await run(page, '2026-03-31');
  const second = (await api(page, headers, '/tasks?limit=1000')).filter(task => task.parent_task_id === original.id);
  expect(second.map(task => task.due_date).sort()).toEqual(['2026-02-28', '2026-03-31']);
  const repeated = await run(page, '2026-03-31');
  expect(repeated.tasks_created).toBe(0);
  expect(repeated.notifications_generated).toBe(0);
  await page.reload();
  await expect(page.getByRole('row').filter({ hasText: title }).filter({ hasText: '31.3.2026' })).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const image = testInfo.outputPath('operational-tasks-mobile.png');
  await page.screenshot({ path: image, fullPage: true });
  await testInfo.attach('operational-tasks-mobile', { path: image, contentType: 'image/png' });
});

test('calendar recurrence: configure a real plan and create each clamped occurrence once', async ({ page }) => {
  const headers = await login(page);
  const title = `Browser Wartung ${randomUUID().slice(0, 8)}`;
  await api(page, headers, '/calendar', { title, event_type: 'maintenance', event_date: '2026-01-31' });
  await page.goto('/calendar');
  await page.getByRole('button', { name: `Wiederholung festlegen ${title}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Wiederholung festlegen', exact: true });
  await dialog.getByLabel(/^Wiederholungsregel/).fill('FREQ=MONTHLY;COUNT=3');
  await dialog.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await run(page, '2026-03-31');
  const dates = async () => (await api(page, headers, '/calendar?limit=1000')).filter(event => event.title === title).map(event => event.event_date).sort();
  expect(await dates()).toEqual(['2026-01-31', '2026-02-28', '2026-03-31']);
  await run(page, '2026-03-31');
  await page.reload();
  expect(await dates()).toEqual(['2026-01-31', '2026-02-28', '2026-03-31']);
  await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(3);
});
