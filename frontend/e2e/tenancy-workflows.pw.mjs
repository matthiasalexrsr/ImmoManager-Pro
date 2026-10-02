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

async function create(page, path, headers, data) {
  const response = await page.request.post(`/api/v1${path}`, { headers, data });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function read(page, path, headers) {
  const response = await page.request.get(`/api/v1${path}`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function fixture(page, headers, tag) {
  const unique = randomUUID();
  const portfolio = await create(page, '/portfolios', headers, { name: `Synthetic workflow ${unique}` });
  const property = await create(page, '/properties', headers, {
    portfolio_id: portfolio.id, name: `Workflow ${tag} ${unique}`, property_type: 'residential',
  });
  const unit = await create(page, '/units', headers, {
    property_id: property.id, label: `Wohnung ${tag}`, unit_type: 'apartment',
  });
  const tenant = await create(page, '/tenants', headers, { full_name: `Synthetic workflow resident ${unique}` });
  const contract = await create(page, '/contracts', headers, {
    contract_number: `Workflow-${tag}-${unique}`, property_id: property.id, unit_id: unit.id,
    tenant_id: tenant.id, status: 'active', start_date: '2026-01-01', end_date: '2030-12-31',
  });
  return { property, unit, contract };
}

async function choose(scope, label, text, { search = true } = {}) {
  if (search) await scope.getByRole('searchbox', { name: new RegExp(`^${label}`) }).fill(text);
  await scope.getByRole('listbox', { name: new RegExp(`^${label}`) })
    .getByRole('option').filter({ hasText: text }).click();
}

function reply(page, method, ending) {
  return page.waitForResponse(response => response.request().method() === method
    && new URL(response.url()).pathname.endsWith(ending));
}

async function result(pending, expected = 200) {
  const response = await pending;
  expect(response.status(), await response.text()).toBe(expected);
  return response.json();
}

async function createTemplate(page, property, title, offset) {
  await page.getByRole('tab', { name: 'Vorlagen & Abläufe', exact: true }).click();
  const form = page.locator('form.workflow-template-create');
  await choose(form, 'Objekt', property.name);
  // The current form exposes this field; the forthcoming UI generates it internally.
  const key = form.getByLabel('Stabiler Schlüssel', { exact: true });
  if (await key.count()) await key.fill(`handover-${randomUUID()}`);
  await form.getByLabel('Titel', { exact: true }).fill(title);
  await form.getByRole('combobox', { name: 'Terminanker', exact: true }).selectOption('move_in_handover');
  await form.getByLabel('Versatz in Tagen', { exact: true }).fill(String(offset));
  const created = reply(page, 'POST', '/workflow-templates');
  await form.getByRole('button', { name: 'Vorlage anlegen', exact: true }).click();
  const draft = await result(created, 201);
  const designer = page.locator('.workflow-template');
  const published = reply(page, 'POST', `/workflow-template-versions/${draft.id}/publish`);
  await designer.getByRole('button', { name: 'Version veröffentlichen', exact: true }).click();
  const version = await result(published);
  expect(version.property_id).toBe(property.id);
  expect(version.state).toBe('published');
  expect(version.steps[0].title).toBe(title);
  expect(version.steps[0].offset_days).toBe(offset);
  return version;
}

async function prepareStart(page, box) {
  await page.getByRole('tab', { name: 'Wechselakte', exact: true }).click();
  const preparation = page.locator('.tenancy-workflow-page__preparation-toggle');
  if (await preparation.getAttribute('aria-expanded') === 'false') await preparation.click();
  await expect(preparation).toHaveAttribute('aria-expanded', 'true');
  const context = page.locator('.tenancy-workflow-page__context');
  await choose(context, 'Objekt', box.property.name);
  await choose(context, 'Einheit', box.unit.label);
  const start = page.locator('.workflow-start');
  await start.getByRole('button', { name: 'Einzug', exact: true }).click();
  await choose(start, 'Neuer Vertrag', box.contract.contract_number);
  await start.getByLabel('Einzugsübergabe', { exact: true }).fill('2026-10-10');
  await choose(start, 'Einzugsvorlage', 'Version 1', { search: false });
  const preview = reply(page, 'POST', '/tenancy-changes/preview');
  await start.getByRole('button', { name: 'Vorschau erstellen', exact: true }).click();
  await result(preview);
  await expect(start.getByRole('button', { name: 'Wechselakte starten', exact: true })).toBeEnabled();
  return start;
}

async function amendTemplate(page, box, version) {
  await page.getByRole('tab', { name: 'Vorlagen & Abläufe', exact: true }).click();
  await page.locator('.tenancy-workflow-page__list').getByRole('button')
    .filter({ hasText: box.property.name }).click();
  const drafted = reply(page, 'POST', `/workflow-templates/${version.template_id}/versions`);
  await page.getByRole('button', { name: 'Neue Entwurfsfassung', exact: true }).click();
  const draft = await result(drafted, 201);
  expect(draft.version).toBe(2);
  const designer = page.locator('.workflow-template');
  await designer.getByLabel('Titel', { exact: true }).fill('Geänderter Ablauf nur für zukünftige Wechsel');
  await designer.getByLabel('Versatz in Tagen', { exact: true }).fill('21');
  const saved = reply(page, 'PUT', `/workflow-template-versions/${draft.id}`);
  await designer.getByRole('button', { name: 'Entwurf speichern', exact: true }).click();
  await result(saved);
  const published = reply(page, 'POST', `/workflow-template-versions/${draft.id}/publish`);
  await designer.getByRole('button', { name: 'Version veröffentlichen', exact: true }).click();
  const amended = await result(published);
  expect(amended.steps[0].stable_key).toBe(version.steps[0].stable_key);
  expect(amended.steps[0].title).toBe('Geänderter Ablauf nur für zukünftige Wechsel');
  expect(amended.steps[0].offset_days).toBe(21);
  return amended;
}

async function noHorizontalOverflow(page, width, testInfo, label) {
  await page.setViewportSize({ width, height: 900 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expect.poll(() => page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }))).toEqual({ viewport: width, content: width });
  await expect.poll(() => page.evaluate(() => {
    const sidebar = document.getElementById('primary-navigation');
    return window.innerWidth > 768
      ? Math.round(sidebar.getBoundingClientRect().left)
      : getComputedStyle(sidebar).visibility;
  })).toBe(width > 768 ? 0 : 'hidden');
  await testInfo.attach(`${label}-${width}-layout`, {
    body: JSON.stringify(await page.evaluate(() => {
      const sidebar = document.getElementById('primary-navigation');
      const rect = sidebar.getBoundingClientRect();
      const style = getComputedStyle(sidebar);
      return { width: window.innerWidth, scrollY: window.scrollY,
        sidebar: { left: rect.left, width: rect.width, visibility: style.visibility, transform: style.transform } };
    })), contentType: 'application/json',
  });
  const viewportPath = testInfo.outputPath(`${label}-${width}-viewport.png`);
  await page.screenshot({ path: viewportPath });
  await testInfo.attach(`${label}-${width}-viewport`, { path: viewportPath, contentType: 'image/png' });
  const path = testInfo.outputPath(`${label}-${width}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(`${label}-${width}`, { path, contentType: 'image/png' });
}

test('object workflows survive a committed lost reply, preserve original dates and complete linked tasks', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  const headers = await login(page);
  const first = await fixture(page, headers, 'A');
  const second = await fixture(page, headers, 'B');
  await page.goto('/tenancy-workflows');
  await expect(page.getByRole('heading', { name: 'Mieterwechsel', level: 1, exact: true })).toBeVisible();
  const firstVersion = await createTemplate(page, first.property, 'Schlüssel und Einzug A vorbereiten', -2);
  const secondVersion = await createTemplate(page, second.property, 'Zähler und Einzug B prüfen', 5);
  expect(secondVersion.property_id).not.toBe(firstVersion.property_id);

  const start = await prepareStart(page, first);
  const commands = [];
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/tenancy-changes') {
      commands.push(request.postDataJSON());
    }
  });
  let committed;
  const pattern = '**/api/v1/tenancy-changes';
  await page.route(pattern, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    expect(response.status(), await response.text()).toBe(201);
    committed = await response.json();
    await route.abort('failed');
  });
  await start.getByRole('button', { name: 'Wechselakte starten', exact: true }).click();
  const exactRetry = start.getByRole('button', { name: /Exakt wiederholen|Aktion erneut prüfen|Erneut prüfen|Unverändert erneut senden/i });
  await expect(exactRetry).toBeVisible();
  await expect(page.locator('.tenancy-workflow-page__preparation-toggle'))
    .toHaveAttribute('aria-expanded', 'true');
  expect(committed.steps).toHaveLength(1);
  expect(committed.steps[0].due_date).toBe('2026-10-08');
  expect(committed.steps[0].original_due_date).toBe('2026-10-08');
  const before = await read(page, `/tenancy-changes?property_id=${first.property.id}`, headers);
  expect(before.items.map(value => value.id)).toEqual([committed.id]);
  await page.unroute(pattern);
  await exactRetry.click();
  const file = page.locator('.workflow-change');
  await expect(file.getByRole('heading', { name: 'Schlüssel und Einzug A vorbereiten', exact: true })).toBeVisible();
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(await read(page, `/tenancy-changes/${committed.id}`, headers)).toEqual(committed);
  expect((await read(page, `/tenancy-changes?property_id=${first.property.id}`, headers)).items).toHaveLength(1);
  await expect(start.getByRole('button', { name: 'Wechselakte starten', exact: true })).toHaveCount(0);
  const reopen = page.getByRole('button', { name: 'Weiteren Wechsel vorbereiten', exact: true });
  await expect(reopen).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.tenancy-workflow-page__context')).toBeHidden();
  await reopen.click();
  await expect(page.locator('.tenancy-workflow-page__context')).toBeVisible();
  await expect(page.locator('.tenancy-workflow-page__context')).toContainText(first.property.name);
  await expect(page.locator('.tenancy-workflow-page__context')).toContainText(first.unit.label);
  await page.getByRole('button', { name: 'Vorbereitung einklappen', exact: true }).click();

  const taskReply = reply(page, 'POST', `/steps/${committed.steps[0].id}/task`);
  await file.getByRole('button', { name: 'Aufgabe verknüpfen/erzeugen', exact: true }).click();
  const linked = await result(taskReply, 201);
  const task = await read(page, `/tasks/${linked.task_id}`, headers);
  expect(task.due_date).toBe('2026-10-08');
  const stepReply = reply(page, 'PATCH', `/steps/${linked.id}`);
  await file.getByRole('button', { name: 'Schritt erledigen', exact: true }).click();
  await result(stepReply);
  await expect(file.getByRole('button', { name: 'Schritt erledigen', exact: true })).toHaveCount(0);
  const completedReply = reply(page, 'POST', `/tenancy-changes/${committed.id}/complete`);
  await file.getByRole('button', { name: 'Wechselakte abschließen', exact: true }).click();
  const completed = await result(completedReply);
  expect(completed.state).toBe('completed');
  expect(completed.steps[0].original_due_date).toBe('2026-10-08');
  expect((await read(page, `/tasks/${linked.task_id}`, headers)).status).toBe('completed');

  await page.reload();
  await page.locator('.tenancy-workflow-page__list').getByRole('button')
    .filter({ hasText: 'Einzug' }).filter({ hasText: 'Abgeschlossen' }).click();
  await expect(file.getByRole('heading', { name: 'Schlüssel und Einzug A vorbereiten', exact: true })).toBeVisible();
  expect((await read(page, `/tenancy-changes/${committed.id}`, headers)).steps[0].original_due_date).toBe('2026-10-08');

  const amended = await amendTemplate(page, first, firstVersion);
  expect(amended.id).not.toBe(firstVersion.id);
  const frozen = await read(page, `/tenancy-changes/${committed.id}`, headers);
  expect(frozen.move_in_template_version_id).toBe(firstVersion.id);
  expect(frozen.steps[0].title_snapshot).toBe('Schlüssel und Einzug A vorbereiten');
  expect(frozen.steps[0].due_date).toBe('2026-10-08');
  expect(frozen.steps[0].original_due_date).toBe('2026-10-08');
  expect(frozen.steps[0].task_id).toBe(linked.task_id);
  expect(frozen.state).toBe('completed');
  expect((await read(page, `/workflow-template-versions/${firstVersion.id}`, headers)).steps)
    .toEqual(firstVersion.steps);

  const secondStart = await prepareStart(page, second);
  const secondReply = reply(page, 'POST', '/tenancy-changes');
  await secondStart.getByRole('button', { name: 'Wechselakte starten', exact: true }).click();
  const other = await result(secondReply, 201);
  expect(other.move_in_template_version_id).toBe(secondVersion.id);
  expect(other.steps[0].title_snapshot).toBe('Zähler und Einzug B prüfen');
  expect(other.steps[0].due_date).toBe('2026-10-15');
  expect(other.steps[0].task_id).toBeNull();
  await expect(file.getByRole('heading', { name: 'Zähler und Einzug B prüfen', exact: true })).toBeVisible();
  await expect(file).toContainText(second.property.name);
  await expect(file).toContainText(second.unit.label);
  await expect(file).toContainText(second.contract.contract_number);
  await expect(page.getByRole('button', { name: 'Weiteren Wechsel vorbereiten', exact: true }))
    .toHaveAttribute('aria-expanded', 'false');
  await noHorizontalOverflow(page, 1440, testInfo, 'workflow-object-B');
  await noHorizontalOverflow(page, 360, testInfo, 'workflow-object-B');
  await noHorizontalOverflow(page, 320, testInfo, 'workflow-object-B');
});
