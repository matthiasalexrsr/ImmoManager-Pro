import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { test as base, expect } from '@playwright/test';
import { extractReportlabText } from './reportlabPdfText.mjs';
import { createPaidMonthlyFixture, assertActualAdvances } from './billingPaidFixture.mjs';

// Reuse the existing isolated SQL-backed runner; never intercept business requests.
const test = base.extend({
  page: async ({ page }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
    await use(page);
    expect(errors, 'No uncaught browser errors').toEqual([]);
  },
});

async function json(page, headers, path, data) {
  const response = await page.request.fetch(`/api/v1${path}`, {
    headers, method: data === undefined ? 'GET' : 'POST', data,
  });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.json();
}

async function scenario(page, costAmount = 800) {
  await page.goto('/login');
  await page.locator('form input[type="text"]').fill('demo');
  await page.locator('form input[type="password"]').fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const health = await (await page.request.get('/health')).json();
  expect(health.store_backend).toBe('SQLAlchemyStore');
  const tag = randomUUID().slice(0, 8);
  const portfolio = await json(page, headers, '/portfolios', { name: `Billing E2E ${tag}` });
  const property = await json(page, headers, '/properties', {
    portfolio_id: portfolio.id, name: `E2E-Haus ${tag}`, property_type: 'MFH',
  });
  const units = [], contracts = [];
  for (const [label, area, advance] of [['Wohnung A', 60, 10], ['Wohnung B', 40, 5]]) {
    const unit = await json(page, headers, '/units', { property_id: property.id,
      label, unit_type: 'Wohnung', area_sqm: area, cold_rent: 100, service_charge_advance: advance * 2, heating_advance: 0 });
    const tenant = await json(page, headers, '/tenants', { full_name: `${label} Test ${tag}` });
    const contract = await json(page, headers, '/contracts', { property_id: property.id,
      unit_id: unit.id, tenant_id: tenant.id, contract_number: `E2E-${tag}-${contracts.length + 1}`,
      start_date: '2025-01-01', status: 'active' });
    units.push(unit); contracts.push(contract);
  }
  const paid = await createPaidMonthlyFixture((path, data) => json(page, headers, path, data), contracts);
  const key = await json(page, headers, '/billing/allocation-keys', {
    property_id: property.id, name: `Fläche ${tag}`, key_type: 'area_sqm',
  });
  const period = await json(page, headers, '/billing/periods', { property_id: property.id,
    label: `Finalisierung ${tag}`, start_date: '2025-01-01', end_date: '2025-12-31', status: 'draft' });
  const cost = await json(page, headers, '/billing/cost-items', { billing_period_id: period.id,
    description: 'Gebäudereinigung', amount: costAmount, allocation_key_id: key.id });
  return { headers, property, units, contracts, key, period, cost, ...paid };
}

const statementTable = page => page.locator('.data-table-wrapper').filter({
  has: page.getByRole('heading', { name: 'Einzelabrechnungen pro Einheit', exact: true }),
});
const costTable = page => page.locator('.data-table-wrapper').filter({
  has: page.getByRole('heading', { name: 'Kostenpositionen', exact: true }),
});
async function openPeriod(page, fixture, amount = 800) {
  await page.goto('/statements');
  const row = page.getByRole('row').filter({ hasText: fixture.property.name })
    .filter({ hasText: `${amount.toFixed(2)} €` });
  await expect(row).toHaveCount(1);
  await row.getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  await expect(page.getByText('Bereit zur Generierung', { exact: true })).toBeVisible();
}
async function postAction(page, button, path, status = 200) {
  const [response] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname === `/api/v1${path}` && res.request().method() === 'POST'),
    page.getByRole('button', { name: button, exact: true }).click(),
  ]);
  expect(response.status(), await response.text()).toBe(status);
  return response.json();
}
async function statements(page, fixture, periodId = fixture.period.id) {
  return json(page, fixture.headers, `/billing/statements?billing_period_id=${periodId}&limit=1000`);
}
const cents = value => Math.round(Number(value) * 100);
const stable = rows => [...rows].sort((a, b) => a.id.localeCompare(b.id));

async function finalizeThroughUi(page, fixture, periodId = fixture.period.id) {
  await postAction(page, 'Abrechnungen generieren', `/billing/periods/${periodId}/generate`, 201);
  await expect(statementTable(page).locator('tbody tr')).toHaveCount(2);
  const savedPeriod = await json(page, fixture.headers, `/billing/periods/${periodId}`);
  expect(savedPeriod.owner_cost_share?.policy).toBe('property_units_occupied_days');
  expect(cents(savedPeriod.owner_cost_share.total_amount)).toBe(0);
  const ownerPanel = page.getByRole('region', { name: 'Eigentümeranteil der Kostenverteilung', exact: true });
  await expect(ownerPanel).toContainText('Dieser Anteil verbleibt beim Eigentümer. Er ist keine Mieterforderung und kein Mieterguthaben.');
  const ownerTotal = ownerPanel.locator('.stat-card').filter({ has: page.getByText('Eigentümeranteil gesamt', { exact: true }) });
  await expect(ownerTotal.locator('.stat-value')).toHaveText('0,00 €');
  await postAction(page, 'Zur Prüfung', `/billing/periods/${periodId}/submit-review`);
  const final = await postAction(page, 'Finalisieren', `/billing/periods/${periodId}/finalize`);
  expect(final.status).toBe('finalized');
  await expect(page.getByRole('button', { name: 'Als zugestellt markieren', exact: true })).toBeVisible();
  const rows = await statements(page, fixture, periodId);
  expect(rows).toHaveLength(2);
  for (const row of rows) {
    expect(row.status).toBe('finalized');
    expect(row.snapshot_hash).toMatch(/^[a-f0-9]{64}$/);
  }
  expect(new Set(rows.map(row => row.snapshot_hash)).size).toBe(1);
  assertActualAdvances(rows, fixture);
  return rows;
}

async function downloadPdf(page, testInfo, statement, unitLabel, name, expectedRevision = 1) {
  const row = statementTable(page).getByRole('row').filter({ hasText: unitLabel });
  const [download, response] = await Promise.all([
    page.waitForEvent('download'),
    page.waitForResponse(res => new URL(res.url()).pathname === `/api/v1/billing/statements/${statement.id}/pdf`),
    row.getByRole('button', { name: 'PDF', exact: true }).click(),
  ]);
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toMatch(/^application\/pdf\b/);
  expect(response.headers()['content-disposition']).toContain(`statement_${statement.id}.pdf`);
  expect(download.suggestedFilename()).toBe(`abrechnung_${statement.id}.pdf`);
  expect(await download.failure()).toBeNull();
  const path = testInfo.outputPath(`${name}.pdf`);
  await download.saveAs(path);
  const bytes = await readFile(path);
  expect(bytes.subarray(0, 8).toString('ascii')).toMatch(/^%PDF-\d\.\d/);
  expect(bytes.subarray(-32).toString('ascii').trimEnd()).toMatch(/%%EOF$/);
  expect(bytes.length).toBeGreaterThan(500);
  // Validate the saved attachment. Edge's DevTools body was empty for this PDF
  // despite a complete Download artifact (recorded in the first-run trace).
  expect(bytes.length).toBe(Number(response.headers()['content-length']));
  const text = extractReportlabText(bytes);
  expect(statement.revision).toBe(expectedRevision);
  const revisions = [...text.matchAll(/\bRevision:\s*(\d+)\b/g)].map(match => Number(match[1]));
  expect(revisions, text).toEqual([expectedRevision]);
  await testInfo.attach(`${name}-text`, { body: text, contentType: 'text/plain' });
  await testInfo.attach(name, { path, contentType: 'application/pdf' });
}

async function mobileEvidence(page, testInfo, name) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: true, animations: 'disabled' });
  await testInfo.attach(name, { path, contentType: 'image/png' });
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  expect(size.document, JSON.stringify(size)).toBeLessThanOrEqual(size.viewport);
}

test('finalization locks costs and persists snapshots with a genuine PDF download', async ({ page }, testInfo) => {
  const fixture = await scenario(page);
  await openPeriod(page, fixture);
  const finalized = await finalizeThroughUi(page, fixture);
  const byUnit = Object.fromEntries(finalized.map(row => [row.unit_id, row]));
  const first = byUnit[fixture.units[0].id], second = byUnit[fixture.units[1].id];
  expect([first.total_cost, first.advance_paid, first.balance].map(cents)).toEqual([48000, 12000, 36000]);
  expect([second.total_cost, second.advance_paid, second.balance].map(cents)).toEqual([32000, 6000, 26000]);
  expect(fixture.period.revision_number).toBe(1);
  expect(fixture.period.source_period_id).toBeNull();
  expect(first.revision).toBe(1);
  expect(first.source_statement_id).toBeNull();
  expect(first.contract_id).toBe(fixture.contracts[0].id);
  expect(second.contract_id).toBe(fixture.contracts[1].id);
  await expect(costTable(page).getByRole('button', { name: 'Neu', exact: true })).toHaveCount(0);
  await expect(costTable(page).getByRole('button', { name: 'Bearbeiten', exact: true })).toHaveCount(0);
  const edit = await page.request.put(`/api/v1/billing/cost-items/${fixture.cost.id}`, {
    headers: fixture.headers, data: { billing_period_id: fixture.period.id,
      allocation_key_id: fixture.key.id, description: fixture.cost.description, amount: 1 },
  });
  expect(edit.status(), await edit.text()).toBe(409);
  const regenerate = await page.request.post(`/api/v1/billing/periods/${fixture.period.id}/generate`, { headers: fixture.headers });
  expect(regenerate.status(), await regenerate.text()).toBe(409);
  await json(page, fixture.headers, `/billing/periods/${fixture.period.id}/finalize`, {});
  expect(stable(await statements(page, fixture))).toEqual(stable(finalized));
  await openPeriod(page, fixture);
  await expect(page.getByRole('button', { name: 'Abrechnungen generieren', exact: true })).toHaveCount(0);
  await expect(statementTable(page).locator('tbody tr')).toHaveCount(2);
  await downloadPdf(page, testInfo, first, fixture.units[0].label, 'finalized-source');
  const anonymous = await page.request.get(`/api/v1/billing/statements/${first.id}/pdf`);
  expect(anonymous.status()).toBe(401);
  await mobileEvidence(page, testInfo, 'finalized-mobile');
});

test('revision copies costs, recalculates independently and preserves the finalized source', async ({ page }, testInfo) => {
  const fixture = await scenario(page);
  await openPeriod(page, fixture);
  const original = await finalizeThroughUi(page, fixture);
  const reason = 'Wasser & Reinigung prüfen';
  await page.getByRole('button', { name: 'Korrektur starten', exact: true }).click();
  await page.getByRole('dialog').getByRole('textbox').fill(reason);
  const revised = await postAction(page, 'Speichern', `/billing/periods/${fixture.period.id}/revisions`);
  expect(revised.source_period_id).toBe(fixture.period.id);
  expect(revised.new_period_id).not.toBe(fixture.period.id);
  expect(revised.revision).toBe(2);
  expect(revised.revision_notes).toBe(reason);
  const revision = await json(page, fixture.headers, `/billing/periods/${revised.new_period_id}`);
  expect(revision.status).toBe('draft');
  expect(revision.source_period_id).toBe(fixture.period.id);
  expect(revision.revision_number).toBe(2);
  expect(revision.revision_notes).toBe(reason);
  await expect(page.getByRole('heading', { name: revision.label, exact: true })).toBeVisible();
  const copied = await json(page, fixture.headers, `/billing/cost-items?billing_period_id=${revision.id}&limit=1000`);
  expect(copied).toHaveLength(1);
  expect(copied[0].id).not.toBe(fixture.cost.id);
  expect(copied[0].allocation_key_id).toBe(fixture.key.id);
  expect(cents(copied[0].amount)).toBe(80000);
  await costTable(page).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Betrag (€)', { exact: false }).fill('900.00');
  const [saved] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname === `/api/v1/billing/cost-items/${copied[0].id}` && res.request().method() === 'PUT'),
    dialog.getByRole('button', { name: 'Speichern', exact: true }).click(),
  ]);
  expect(saved.status()).toBe(200);
  await expect(costTable(page).getByRole('cell', { name: '900.00 €', exact: true })).toBeVisible();
  const correction = await finalizeThroughUi(page, fixture, revision.id);
  expect(correction.reduce((total, row) => total + cents(row.total_cost), 0)).toBe(90000);
  expect(correction.every(row => row.snapshot_hash !== original[0].snapshot_hash)).toBe(true);
  expect(correction.every(row => !original.some(source => source.id === row.id))).toBe(true);
  for (const row of correction) {
    expect(row.revision).toBe(2);
    expect(row.revision_notes).toBe(reason);
    expect(row.source_statement_id).toBe(original.find(source => source.contract_id === row.contract_id).id);
  }
  const first = correction.find(row => row.unit_id === fixture.units[0].id);
  expect([first.total_cost, first.advance_paid, first.balance].map(cents)).toEqual([54000, 12000, 42000]);
  expect(stable(await statements(page, fixture))).toEqual(stable(original));
  expect(cents((await json(page, fixture.headers, `/billing/cost-items/${fixture.cost.id}`)).amount)).toBe(80000);
  await openPeriod(page, fixture, 900);
  await expect(page.getByRole('heading', { name: revision.label, exact: true })).toBeVisible();
  expect(stable(await statements(page, fixture, revision.id))).toEqual(stable(correction));
  await downloadPdf(page, testInfo, first, fixture.units[0].label, 'finalized-revision', 2);
  const recordPath = testInfo.outputPath('revision-records.json');
  await writeFile(recordPath, JSON.stringify({ revisionResponse: revised, original, correction }, null, 2));
  await testInfo.attach('revision-records', { path: recordPath, contentType: 'application/json' });
  await mobileEvidence(page, testInfo, 'revision-mobile');
});

test('finalization without generated statements reports the backend rejection visibly', async ({ page }) => {
  const fixture = await scenario(page);
  await openPeriod(page, fixture);
  await postAction(page, 'Zur Prüfung', `/billing/periods/${fixture.period.id}/submit-review`);
  await postAction(page, 'Finalisieren', `/billing/periods/${fixture.period.id}/finalize`, 400);
  await expect(page.getByRole('alert')).toContainText('Einzelabrechnungen fehlen; bitte vollständig neu erzeugen.');
  expect((await json(page, fixture.headers, `/billing/periods/${fixture.period.id}`)).status).toBe('review');
  expect(await statements(page, fixture)).toEqual([]);
  await expect(page.getByRole('button', { name: 'Abrechnungen generieren', exact: true })).toBeEnabled();
});

async function postSettlements(page, fixture, periodId, expected) {
  const result = await postAction(page, 'Forderungen und Guthaben verbuchen', `/billing/periods/${periodId}/create-receivables`);
  expect(result.period_id).toBe(periodId);
  expect(result.settlements).toHaveLength(2);
  for (const key of ['debts_total', 'credits_total', 'net_amount']) expect(cents(result[key]), key).toBe(cents(expected[key]));
  for (const key of ['created_receivables', 'created_credits', 'created_settlements', 'existing_count']) expect(result[key], key).toBe(expected[key]);
  const persisted = await json(page, fixture.headers, `/billing/periods/${periodId}/settlements`);
  expect(stable(persisted.settlements)).toEqual(stable(result.settlements));
  const region = page.getByRole('region', { name: 'Verbuchte Abrechnungsergebnisse', exact: true });
  const money = value => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(value);
  for (const [label, key] of [['Verbuchte Forderungen', 'debts_total'], ['Verfügbare Guthaben', 'credits_total'], ['Netto (Forderungen − Guthaben)', 'net_amount']]) {
    const card = region.locator('.stat-card').filter({ has: page.getByText(label, { exact: true }) });
    await expect(card.locator('.stat-value')).toHaveText(money(expected[key]));
  }
  await expect(region).toContainText('Guthaben sind verfügbar. Eine Auszahlung wird hier weder erfasst noch bestätigt.');
  for (const record of result.settlements) {
    expect(record.billing_period_id).toBe(periodId);
    if (record.kind === 'credit') {
      expect(record.status).toBe('credit_available');
      expect(record.receivable_id).toBeNull();
      expect(cents(record.signed_amount)).toBeLessThan(0);
    } else if (record.kind === 'debt') {
      const claim = await json(page, fixture.headers, `/receivables/${record.receivable_id}`);
      expect(claim.statement_id).toBe(record.statement_id);
      expect(cents(claim.amount_due)).toBe(cents(record.signed_amount));
      expect(cents(claim.amount_due)).toBeGreaterThan(0);
    }
  }
  return result;
}

async function reviseCostThroughUi(page, fixture, sourceId, amount, reason, expectedRevision) {
  await page.getByRole('button', { name: 'Korrektur starten', exact: true }).click();
  await page.getByRole('dialog').getByRole('textbox').fill(reason);
  const response = await postAction(page, 'Speichern', `/billing/periods/${sourceId}/revisions`);
  expect(response.revision).toBe(expectedRevision);
  const period = await json(page, fixture.headers, `/billing/periods/${response.new_period_id}`);
  expect(period.source_period_id).toBe(sourceId);
  expect(period.revision_number).toBe(expectedRevision);
  expect(period.revision_notes).toBe(reason);
  await expect(page.getByRole('heading', { name: period.label, exact: true })).toBeVisible();
  const costs = await json(page, fixture.headers, `/billing/cost-items?billing_period_id=${period.id}&limit=1000`);
  expect(costs).toHaveLength(1);
  await costTable(page).getByRole('button', { name: 'Bearbeiten', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Betrag (€)', { exact: false }).fill(amount.toFixed(2));
  const [saved] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname === `/api/v1/billing/cost-items/${costs[0].id}` && res.request().method() === 'PUT'),
    dialog.getByRole('button', { name: 'Speichern', exact: true }).click(),
  ]);
  expect(saved.status()).toBe(200);
  await expect(costTable(page).getByRole('cell', { name: `${amount.toFixed(2)} €`, exact: true })).toBeVisible();
  return period;
}

test('available credits persist without creating negative receivables or claiming a payout', async ({ page }, testInfo) => {
  const fixture = await scenario(page, 50);
  await openPeriod(page, fixture, 50);
  const rows = await finalizeThroughUi(page, fixture);
  expect(rows.map(row => cents(row.balance)).sort((a, b) => a - b)).toEqual([-9000, -4000]);
  const expected = { debts_total: 0, credits_total: 130, net_amount: -130,
    created_receivables: 0, created_credits: 2, created_settlements: 2, existing_count: 0 };
  const posted = await postSettlements(page, fixture, fixture.period.id, expected);
  expect(posted.settlements.every(row => row.kind === 'credit' && row.receivable_id === null)).toBe(true);
  const repeated = await postSettlements(page, fixture, fixture.period.id, { ...expected,
    created_credits: 0, created_settlements: 0, existing_count: 2 });
  expect(stable(repeated.settlements)).toEqual(stable(posted.settlements));
  for (const contract of fixture.contracts) {
    expect(await json(page, fixture.headers, `/receivables?contract_id=${contract.id}&limit=1000`)).toEqual([]);
  }
  await openPeriod(page, fixture, 50);
  const persisted = await json(page, fixture.headers, `/billing/periods/${fixture.period.id}/settlements`);
  expect(stable(persisted.settlements)).toEqual(stable(posted.settlements));
  const region = page.getByRole('region', { name: 'Verbuchte Abrechnungsergebnisse', exact: true });
  await expect(region.getByText('Guthaben verfügbar (keine Auszahlung bestätigt)', { exact: true })).toHaveCount(2);
  await mobileEvidence(page, testInfo, 'available-credit-mobile');
});

test('revision chain books only deltas and prints persistent revision three', async ({ page }, testInfo) => {
  const fixture = await scenario(page);
  await openPeriod(page, fixture);
  const original = await finalizeThroughUi(page, fixture);
  const sourcePosting = await postSettlements(page, fixture, fixture.period.id, {
    debts_total: 620, credits_total: 0, net_amount: 620,
    created_receivables: 2, created_credits: 0, created_settlements: 2, existing_count: 0,
  });
  const revision2 = await reviseCostThroughUi(page, fixture, fixture.period.id, 900, 'Additional cleaning', 2);
  const second = await finalizeThroughUi(page, fixture, revision2.id);
  expect(second.every(row => row.revision === 2)).toBe(true);
  const additional = await postSettlements(page, fixture, revision2.id, {
    debts_total: 100, credits_total: 0, net_amount: 100,
    created_receivables: 2, created_credits: 0, created_settlements: 2, existing_count: 0,
  });
  const revision3 = await reviseCostThroughUi(page, fixture, revision2.id, 700, 'Corrected supplier invoice', 3);
  const third = await finalizeThroughUi(page, fixture, revision3.id);
  for (const row of third) {
    expect(row.revision).toBe(3);
    expect(row.revision_notes).toBe('Corrected supplier invoice');
    expect(row.source_statement_id).toBe(second.find(source => source.contract_id === row.contract_id).id);
  }
  const credited = await postSettlements(page, fixture, revision3.id, {
    debts_total: 0, credits_total: 200, net_amount: -200,
    created_receivables: 0, created_credits: 2, created_settlements: 2, existing_count: 0,
  });
  expect(credited.settlements.map(row => cents(row.signed_amount)).sort((a, b) => a - b)).toEqual([-12000, -8000]);
  for (const record of credited.settlements) {
    expect(record.root_statement_id).toBe(original.find(row => row.contract_id === record.contract_id).id);
    expect(record.source_statement_id).toBe(second.find(row => row.contract_id === record.contract_id).id);
  }
  expect(stable(await statements(page, fixture))).toEqual(stable(original));
  expect(stable(await statements(page, fixture, revision2.id))).toEqual(stable(second));
  const oldClaimIds = [...sourcePosting.settlements, ...additional.settlements].map(row => row.receivable_id).sort();
  const claims = (await Promise.all(fixture.contracts.map(contract =>
    json(page, fixture.headers, `/receivables?contract_id=${contract.id}&limit=1000`)))).flat();
  expect(claims.map(row => row.id).sort()).toEqual(oldClaimIds);
  expect(claims.every(row => Number(row.amount_due) > 0)).toBe(true);
  await openPeriod(page, fixture, 700);
  const persisted = await json(page, fixture.headers, `/billing/periods/${revision3.id}`);
  expect(persisted).toMatchObject({ source_period_id: revision2.id, revision_number: 3,
    revision_notes: 'Corrected supplier invoice', status: 'finalized' });
  const first = third.find(row => row.unit_id === fixture.units[0].id);
  expect([first.total_cost, first.advance_paid, first.balance].map(cents)).toEqual([42000, 12000, 30000]);
  await downloadPdf(page, testInfo, first, fixture.units[0].label, 'finalized-revision-three', 3);
  await testInfo.attach('settlement-chain', { body: JSON.stringify({ original, second, third,
    sourcePosting, additional, credited }, null, 2), contentType: 'application/json' });
  await mobileEvidence(page, testInfo, 'revision-three-credit-mobile');
});
