import { describe, expect, it } from 'vitest';
import { parseOwnerCostShare } from '../utils/billingOwnerShare';
import { ownerPeriod } from './fixtures/ownerShare';

describe('saved owner allocation contract', () => {
  it('keeps owner120 separate from tenant50 out of property170', () => {
    const result = parseOwnerCostShare(ownerPeriod(), 'period');
    expect(result.total_amount).toBe(120);
    expect(result.tenant_cost_total).toBe(50);
    expect(result.property_cost_total).toBe(170);
    expect(result.line_items.map(line => line.allocated_amount)).toEqual([50, 70]);
  });
  it('distinguishes an uncalculated null snapshot from a zero owner allocation', () => {
    expect(parseOwnerCostShare({ id: 'period', owner_cost_share: null }, 'period')).toBeNull();
    const body = ownerPeriod();
    Object.assign(body.owner_cost_share, { total_amount: 0, recoverable_vacancy_amount: 0,
      non_recoverable_amount: 0, property_cost_total: 100, tenant_cost_total: 100, line_items: [], vacant_unit_days: {} });
    expect(parseOwnerCostShare(body, 'period').total_amount).toBe(0);
  });
  it.each([
    body => { body.id = 'other'; },
    body => { delete body.owner_cost_share; },
    body => { body.owner_cost_share.total_amount = 0; },
    body => { body.owner_cost_share.property_cost_total = 50; },
    body => { body.owner_cost_share.total_amount = null; },
    body => { body.owner_cost_share.total_amount = ' '; },
    body => { body.owner_cost_share.total_amount = 'Infinity'; },
    body => { body.owner_cost_share.line_items = []; },
    body => { body.owner_cost_share.policy = 'unknown'; },
    body => { body.owner_cost_share.vacant_unit_days = []; },
    body => { body.owner_cost_share.vacant_unit_days.vacant = -1; },
    body => { body.owner_cost_share.line_items[0].reason = 'tenant_debt'; },
    body => { body.owner_cost_share.line_items[0].allocated_amount = 50.001; },
    body => { body.owner_cost_share.line_items[0].unit_id = null; },
  ])('rejects partial or inconsistent owner data (%#)', mutate => {
    const body = ownerPeriod();
    mutate(body);
    expect(() => parseOwnerCostShare(body, 'period')).toThrow('Invalid owner cost share response');
  });
});
