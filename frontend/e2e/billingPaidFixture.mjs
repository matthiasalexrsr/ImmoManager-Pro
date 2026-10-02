import { randomUUID } from 'node:crypto';
import { expect } from '@playwright/test';
const cents = value => Math.round(Number(value) * 100);

// Used only with the existing runner's fresh test database. No user data or money
// transfer: these are synthetic ledger receipts posted through the actual API.
export async function createPaidMonthlyFixture(request, contracts) {
  const generation = { start_month: '2025-01', end_month: '2025-12', contract_ids: contracts.map(row => row.id) };
  const preview = await request('/rent-charges/preview', generation);
  expect(preview.candidates).toHaveLength(24);
  const generated = await request('/rent-charges/generate', { ...generation, preview_hash: preview.preview_hash });
  expect(generated.created_count).toBe(24);
  expect(generated.created).toHaveLength(24);
  const receipts = [];
  for (const charge of generated.created) {
    const first = charge.contract_id === contracts[0].id;
    expect(cents(charge.cold_rent)).toBe(10000);
    expect(cents(charge.service_charge)).toBe(first ? 2000 : 1000);
    // Half of 120/110 monthly rent pays 10/5 service advance: 120/60 for the year.
    const amount = first ? 60 : 55;
    const receipt = await request(`/rent-charges/${charge.id}/payments`, {
      amount, payment_date: `${charge.month}-03`, note: 'Synthetic billing E2E fixture', idempotency_key: randomUUID(),
    });
    const saved = await request(`/rent-charges/${charge.id}/payments`);
    expect(saved.map(row => row.id)).toEqual([receipt.id]);
    expect(cents(saved[0].amount)).toBe(cents(amount));
    const savedCharge = await request(`/rent-charges/${charge.id}`);
    expect(savedCharge.status).toBe('partial');
    expect(cents(savedCharge.amount_paid)).toBe(cents(amount));
    receipts.push(receipt);
  }
  return { rentCharges: generated.created, receipts };
}

export function assertActualAdvances(rows, fixture) {
  for (const row of rows) {
    const first = row.contract_id === fixture.contracts[0].id;
    const monthlyAdvance = first ? 10 : 5;
    expect(cents(row.advance_paid)).toBe(cents(monthlyAdvance * 12));
    expect(row.advance_details).toHaveLength(12);
    expect(new Set(row.advance_details.map(detail => detail.month)).size).toBe(12);
    for (const detail of row.advance_details) {
      const charge = fixture.rentCharges.find(item => item.id === detail.rent_charge_id);
      expect(charge?.contract_id).toBe(row.contract_id);
      expect(detail.month).toBe(charge.month);
      expect(cents(detail.advance_paid)).toBe(cents(monthlyAdvance));
      expect(cents(detail.paid_at_cutoff)).toBe(first ? 6000 : 5500);
      expect(cents(detail.split.service_charge)).toBe(cents(monthlyAdvance));
      expect(cents(detail.split.cold_rent)).toBe(5000);
      const receiptIds = fixture.receipts.filter(receipt => receipt.entity_id === charge.id).map(receipt => receipt.id).sort();
      expect(receiptIds).toHaveLength(1);
      expect([...detail.receipt_ids].sort()).toEqual(receiptIds);
      expect(cents(detail.receipt_paid_at_cutoff)).toBe(first ? 6000 : 5500);
      expect(detail.excluded_receipts).toEqual([]);
      expect(detail.reversals_after_cutoff).toEqual([]);
      expect(detail.legacy_undated_paid).toBe(0);
      expect(detail.cutoff).toBe('2025-12-31');
      expect(detail.policy).toBe('proportional_largest_remainder');
    }
  }
}
