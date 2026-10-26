import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';

/** Exercise the critical confirmations in the UI; setup uses the same authorized public APIs. */
export async function turnoverJourney({ page, api, call, base, fixture, expect, shot, download, hash }) {
  const unit = await call('POST', '/units', { property_id: fixture.property.id, label: 'QA Mietwechsel',
    unit_type: 'residential', rooms: 2, area_sqm: 60, cold_rent: 500 });
  const old = await call('POST', '/contracts', { contract_number: 'QA-ENDE-1', property_id: fixture.property.id,
    unit_id: unit.id, tenant_id: fixture.households[0].tenant.id, start_date: '2025-01-01',
    end_date: '2026-10-01', status: 'expired', deposit_amount: 1500 });
  const meter = await call('POST', '/meters', { unit_id: unit.id, meter_type: 'cold_water', serial_number: 'QA-MET-1' });
  const workflow = async () => (await call('GET', '/work-center/items?kind=contract_end')).items.find(row => row.entity_id === old.id);
  assert.equal((await workflow()).workflow.stage, 'handover');
  let detail = await call('POST', '/handover-protocols/from-contract', { contract_id: old.id, protocol_type: 'move_out' });
  const protocol = detail.protocol;
  const body = Object.fromEntries(['protocol_date', 'tenant_present', 'landlord_present', 'overall_condition',
    'notes', 'tenant_signature', 'landlord_signature'].map(key => [key, protocol[key]]));
  detail = await call('PUT', '/handover-protocols/' + protocol.id + '/content', { ...body, base_revision: protocol.revision,
    rooms: detail.rooms.map(room => ({ id: room.id, name: room.name, condition: 'good', notes: null })), defects: [],
    keys: [{ id: randomUUID(), key_type: 'apartment_door', label: 'Wohnung', handed_over: 2, returned: 2, notes: null }],
    meter_readings: [{ id: randomUUID(), meter_id: meter.id, meter_type: null, meter_number: null, reading_value: 130, unit: null, notes: null }] });
  await page.goto(base.origin + '/handover-protocols?focus_id=' + protocol.id);
  const dialog = page.getByRole('dialog', { name: /^Übergabeprotokoll/ });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Unterschrift Vermieter / Beauftragte (Name)').fill('QA Verwaltung');
  await dialog.getByRole('button', { name: 'Prüfen', exact: true }).click();
  await dialog.getByLabel('Ich bestätige, dass das Protokoll den gemeinsam festgestellten Zustand wiedergibt.').check();
  await dialog.getByLabel('Ich bestätige, dass die genannten Personen das ausgedruckte Protokoll unterschreiben bzw. unterschrieben haben.').check();
  await dialog.getByRole('button', { name: 'Abschließen und Original speichern' }).click();
  await expect(dialog.getByText('Abgeschlossen: Das PDF ist als unveränderliches Original gespeichert, die Zählerstände stehen in der Abrechnung.')).toBeVisible();
  detail = await call('GET', '/handover-protocols/' + protocol.id + '/detail');
  assert.ok(detail.protocol.finalized_at); assert.ok(detail.protocol.document_id);
  assert.ok(detail.meter_readings[0].standalone_reading_id);
  const pdf = await download(page, dialog.getByRole('button', { name: 'PDF herunterladen', exact: true }), 'turnover-original.pdf');
  assert.ok(pdf.subarray(0, 5).toString() === '%PDF-'); assert.equal(hash(pdf), detail.original.pdf_sha256);
  assert.equal((await workflow()).workflow.stage, 'reletting');
  await shot('turnover-handover');

  let letting = await call('POST', '/reletting', { unit_id: unit.id });
  const pid = letting.project.id;
  letting = await call('PUT', '/reletting/' + pid, { base_updated_at: letting.project.updated_at,
    available_from: '2026-11-01', target_rent: 800, service_charge: 150, heating_charge: 50,
    deposit_amount: 2400, income_factor: 3, max_persons: 3, pets: 'not_allowed',
    headline: 'QA Wohnung zum Mietwechsel', description: 'Geprüfte synthetische Neuvermietung.',
    contact_name: 'QA Verwaltung', contact_email: 'qa@example.invalid', contact_phone: '030123456' });
  letting = await call('POST', '/reletting/' + pid + '/applicants', { full_name: 'QA Neue Mietpartei',
    email: 'qa-neu@example.invalid', phone: '030123456', household_size: 2, net_income: 3200,
    employment: 'permanent', move_in_date: '2026-11-01', pets: 'keine', doc_self_disclosure: true,
    doc_income: true, doc_credit_report: true, doc_landlord_reference: true, doc_id_checked: true });
  const accepted = await call('POST', '/reletting/' + pid + '/accept', { lead_id: letting.applicants[0].id });
  const successor = await call('POST', '/contracts', { ...accepted.contract_prefill, contract_number: 'QA-NEU-1' });
  assert.equal(successor.unit_id, old.unit_id);
  const rents = await call('GET', '/contracts/current-rents?as_of=2026-11-15');
  assert.equal(rents[successor.id].cold_rent, 800);
  assert.equal((await call('GET', '/contracts/current-rents?as_of=2026-09-15'))[old.id].cold_rent, 500);
  await page.goto(base.origin + '/reletting/' + pid + '?tab=closing');
  await page.getByLabel('Vertrag', { exact: true }).selectOption(successor.id);
  await page.getByRole('button', { name: 'Projekt abschließen (vermietet)' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click();
  await expect.poll(async () => (await call('GET', '/reletting/' + pid)).project.status).toBe('closed');
  assert.equal((await workflow()).workflow.stage, 'deposit');
  await shot('turnover-reletting');

  const bookingCount = (await call('GET', '/bookings?limit=1000')).length;
  let security = await call('POST', '/deposits/agreements', { contract_id: old.id, amount: 1500,
    form: 'guarantee', instalment_count: 1, account_id: null, institution: 'QA Bank',
    account_reference: 'QA Bürgschaft', account_holder: 'QA Verwaltung' });
  const depositId = security.deposit.id;
  security = await call('PUT', '/deposits/' + depositId + '/security', { base_revision: security.deposit.revision, provided_on: '2025-01-01' });
  const incomplete = await api.put(base.origin + '/api/v1/deposits/' + depositId + '/security', {
    data: { base_revision: security.deposit.revision, provided_on: '2025-01-01', released_on: '2026-10-26' } });
  assert.equal(incomplete.status(), 400);
  await page.goto(base.origin + '/deposits?contract_id=' + old.id + '&deposit_id=' + depositId);
  const panel = page.getByRole('region', { name: 'Sicherheit', exact: true });
  await panel.getByLabel('Freigegeben am').fill('2026-10-26');
  await panel.getByLabel('Vermerk zur Freigabe').fill('Bürgschaftsurkunde nach geprüfter Übergabe im Original an die Bank zurückgegeben.');
  await panel.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect.poll(async () => (await call('GET', '/deposits/' + depositId + '/file')).stage).toBe('released');
  assert.equal((await call('GET', '/bookings?limit=1000')).length, bookingCount);
  const finished = await workflow();
  assert.ok(!finished || finished.workflow.completed);
  await shot('turnover-deposit');
  await page.setViewportSize({ width: 390, height: 844 }); await shot('turnover-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });
}
