import { createHash, randomUUID } from 'node:crypto';
import { expect } from '@playwright/test';
import { germanWorkspaceReady } from './demoFixtures.mjs';
import { createPaidMonthlyFixture } from './billingPaidFixture.mjs';

export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export const draftPath = (actorId, periodId, caseId = '') => `/auth/users/me/form-drafts?${new URLSearchParams({
  collection: 'billing/disputes', owner_id: actorId, form_key: `${caseId ? 'event' : 'open'}:${caseId || periodId}` })}`;

export async function login(page, username = 'demo', password = 'Demo1234') {
  // Persist real preferences before mounting the actual login UI. No token or
  // AuthContext response is supplied by the browser test.
  const auth = await page.request.post('/api/v1/auth/login', { data: { username, password } });
  expect(auth.status(), await auth.text()).toBe(200);
  const preliminary = (await auth.json()).access_token;
  const preferences = await page.request.put('/api/v1/auth/users/me/preferences', {
    headers: { Authorization: `Bearer ${preliminary}` }, data: { locale: 'de-DE', theme: 'light', sidebar_collapsed: false } });
  expect(preferences.status(), await preferences.text()).toBe(200);
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/); await germanWorkspaceReady(page);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

export function nativeApi(page, headers) {
  return async (path, data, method = data === undefined ? 'GET' : 'POST', status) => {
    const response = await page.request.fetch(`/api/v1${path}`, { headers, method, ...(data === undefined ? {} : { data }) });
    if (status !== undefined) expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
    else expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
    if (response.status() === 204) return null;
    expect(response.headers()['content-type'], `${path}: the actual API must return JSON`).toMatch(/^application\/json(?:;|$)/);
    return response.json();
  };
}

export async function finalize(api, periodId) {
  const generated = await api(`/billing/periods/${periodId}/generate`, {}, 'POST', 201);
  expect(generated).toHaveLength(2);
  await api(`/billing/periods/${periodId}/submit-review`, {}, 'POST', 200);
  const period = await api(`/billing/periods/${periodId}/finalize`, {}, 'POST', 200);
  expect(period.status).toBe('finalized');
  // Two known exact IDs, never a complete statement inventory selector.
  const statements = [];
  for (const row of generated) {
    const actual = await api(`/billing/statements/${row.id}`);
    expect(actual.status).toBe('finalized'); expect(actual.snapshot_hash).toMatch(/^[0-9a-f]{64}$/); statements.push(actual);
  }
  return { period, statements };
}

export async function fixture(page, versions = 1) {
  const headers = await login(page); const api = nativeApi(page, headers); const actor = await api('/auth/me');
  const health = await (await page.request.get('/health')).json();
  expect(health).toMatchObject({ store_backend: 'SQLAlchemyStore', database_connected: true });
  const tag = randomUUID(); const portfolio = await api('/portfolios', { name: `C Browser ${tag}` }, 'POST', 201);
  const property = await api('/properties', { portfolio_id: portfolio.id, name: `C Originalhaus ${tag}`, property_type: 'MFH' }, 'POST', 201);
  const units = [], tenants = [], contracts = [];
  for (const [label, area, advance] of [['A', 60, 20], ['B', 40, 10]]) {
    const unit = await api('/units', { property_id: property.id, label: `C Wohnung ${label} ${tag}`, unit_type: 'Wohnung', area_sqm: area,
      cold_rent: 100, service_charge_advance: advance, heating_advance: 0 }, 'POST', 201);
    const tenant = await api('/tenants', { full_name: `C Originalperson ${label} ${tag}`, address_line: 'Synthetischer Originalweg 3', postal_code: '12345', city: 'Originalstadt', country: 'DE' }, 'POST', 201);
    const contract = await api('/contracts', { property_id: property.id, unit_id: unit.id, tenant_id: tenant.id, contract_number: `C-${label}-${tag}`, start_date: '2025-01-01', status: 'active' }, 'POST', 201);
    units.push(unit); tenants.push(tenant); contracts.push(contract);
  }
  await createPaidMonthlyFixture(api, contracts);
  const allocation = await api('/billing/allocation-keys', { property_id: property.id, name: `C Fläche ${tag}`, key_type: 'area_sqm' }, 'POST', 201);
  const period = await api('/billing/periods', { property_id: property.id, label: `C Abrechnung ${tag}`, start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' }, 'POST', 201);
  await api('/billing/cost-items', { billing_period_id: period.id, description: 'Synthetische Reinigung', amount: 800, allocation_key_id: allocation.id }, 'POST', 201);
  const final = await finalize(api, period.id);
  const statement = final.statements.find(row => row.contract_id === contracts[0].id); expect(statement).toBeTruthy();
  const originalBytes = Buffer.from(`C actual archived original ${tag}\nOriginal äöüß €.\n`);
  const upload = await page.request.post('/api/v1/files/upload', { headers, multipart: { file: { name: `C-Original-${tag}.txt`, mimeType: 'text/plain', buffer: originalBytes } } });
  expect(upload.status(), await upload.text()).toBe(200);
  const uploaded = await upload.json();
  const document = await api('/documents', { title: `C Originalanlage ${tag}`, document_type: 'Beleg', property_id: property.id,
    unit_id: units[0].id, contract_id: contracts[0].id, tenant_id: tenants[0].id, file_url: uploaded.file_url }, 'POST', 201);
  const source = await api(`/documents/${document.id}/version-source`);
  expect(source.sha256).toBe(sha256(originalBytes)); expect(source.size_bytes).toBe(originalBytes.length);
  const original = await api(`/documents/${document.id}/versions/archive-original`, { idempotency_key: randomUUID(), expected_document_etag: source.document_etag,
    expected_head_id: null, expected_sha256: source.sha256, comment: 'Explicit synthetic original archive', confirmed: true }, 'POST', 201);
  expect(original.number).toBe(1); expect(original.sha256).toBe(source.sha256);
  for (let number = 2; number <= versions; number += 1) {
    const head = await api(`/documents/${document.id}/versions?limit=1`);
    const published = await page.request.post(`/api/v1/documents/${document.id}/versions`, { headers, multipart: {
      command: JSON.stringify({ idempotency_key: randomUUID(), expected_document_etag: head.document_etag, expected_head_id: head.head.id,
        comment: `Synthetic archived revision ${number}`, confirmed: true }),
      file: { name: `C-Version-${number}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`Actual small archived revision ${number}: ${tag}\n`) },
    } });
    expect(published.status(), await published.text()).toBe(201); expect((await published.json()).number).toBe(number);
  }
  const metadata = await api(`/workflow-references/statements?${new URLSearchParams({ period_id: period.id, selected_id: statement.id, page_size: '25' })}`);
  expect(metadata.selected).toMatchObject({ id: statement.id, revision: statement.revision, snapshot_hash: statement.snapshot_hash });
  return { api, headers, actor, tag, portfolio, property, units, tenants, contracts, period: final.period, statement,
    statementLabel: metadata.selected.label, document, original, originalBytes };
}

export async function openPeriod(page, box) {
  await page.goto('/statements');
  const row = page.getByRole('row').filter({ has: page.getByText(box.period.label, { exact: true }) });
  await expect(row).toHaveCount(1); await row.click();
  await expect(page.getByRole('region', { name: 'Widerspruchsakten', exact: true })).toBeVisible();
}

export async function newOpen(page, box, evidence = false) {
  await page.getByRole('button', { name: 'Neue Akte erfassen', exact: true }).click(); const form = page.locator('.dispute-command');
  await expect(form.getByText('Entwurfsschutz bereit', { exact: true })).toBeVisible();
  await form.getByLabel('Grund / Notiz', { exact: true }).fill(`Originaler Eingang ${box.tag}`);
  await form.getByLabel('Tatsächlicher Eingang', { exact: true }).fill('2026-10-01');
  await form.getByRole('button', { name: box.statementLabel, exact: true }).click();
  await form.getByRole('button', { name: 'Geprüften Originalstand übernehmen', exact: true }).click();
  await form.getByRole('checkbox', { name: /^Position 1:/ }).check();
  if (evidence) {
    const documents = form.getByRole('group', { name: 'Dokument', exact: true });
    await documents.getByRole('searchbox').fill(box.document.title);
    await documents.getByRole('button', { name: box.document.title, exact: true }).click();
    const versions = form.getByRole('region', { name: 'Archivierte Originalversion', exact: true });
    await expect(versions.locator('.dispute-version-list > li').first()).toBeVisible();
    const oldest = versions.getByRole('button', { name: `Version 1 · ${box.original.filename}`, exact: true });
    if (await oldest.count() === 0) await versions.getByRole('button', { name: 'Nächste Seite', exact: true }).click();
    await oldest.click();
  }
  await form.getByRole('button', { name: 'Vorschau prüfen', exact: true }).click();
  await expect(form.getByRole('region', { name: 'Geprüfte Vorschau', exact: true })).toBeVisible();
  return form;
}

export async function openNative(box) {
  const input = { idempotency_key: randomUUID(), reason: `Native original ${box.tag}`, evidence_version_ids: [box.original.id], expected_case_revision: 0,
    case_kind: 'tenant_statement', period_id: box.period.id, statement_id: box.statement.id, expected_statement_revision: box.statement.revision,
    expected_snapshot_hash: box.statement.snapshot_hash, received_on: '2026-10-01', line_item_refs: [0] };
  const reviewed = await box.api('/billing/disputes/preview', input, 'POST', 200);
  return box.api('/billing/disputes', { ...reviewed.request, preview_hash: reviewed.preview_hash }, 'POST', 201);
}

export async function appendNative(box, caseId, kind, reason) {
  const actual = await box.api(`/billing/disputes/${caseId}`);
  const input = { idempotency_key: randomUUID(), reason, evidence_version_ids: [], expected_revision: actual.revision, kind, observed_on: '2026-10-02', corrects_event_id: null, correction_statement_id: null };
  const reviewed = await box.api(`/billing/disputes/${caseId}/preview`, input, 'POST', 200);
  return box.api(`/billing/disputes/${caseId}/events`, { ...reviewed.request, preview_hash: reviewed.preview_hash }, 'POST', 200);
}

export async function responsive(page, testInfo, name) {
  for (const width of [1440, 360, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    const path = testInfo.outputPath(`${name}-${width}.png`); await page.screenshot({ path, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`${name}-${width}`, { path, contentType: 'image/png' });
    // Keep the actual file context legible even when the complete chronology
    // makes the full-page image much taller than one screen.
    const preview = page.locator('.dispute-preview'); const cases = page.locator('.dispute-case');
    const target = await preview.count() ? preview : await cases.count() ? cases : page.locator('.billing-disputes').first();
    await target.locator('h2, h3, [role="alert"]').first().scrollIntoViewIfNeeded();
    const detail = testInfo.outputPath(`${name}-${width}-detail.png`); await page.screenshot({ path: detail, animations: 'disabled' });
    await testInfo.attach(`${name}-${width}-detail`, { path: detail, contentType: 'image/png' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}

export const financialIdentity = row => Object.fromEntries(['id', 'revision', 'total_cost', 'advance_paid', 'balance', 'snapshot_hash', 'status', 'delivery_status', 'delivered_at'].map(key => [key, row[key]]));
