import { describe, expect, it } from 'vitest';
import { contractPhase, currentContractsOn, localDay, occupancyOn } from '../utils/occupancy';

const day = '2026-10-16';
const active = { id: 'current', unit_id: 'u1', tenant_id: 't1', status: 'active', start_date: '2025-01-01' };
describe('calendar-day contract classification', () => {
  it('retains a terminated tenancy until the inclusive last day and excludes future or expired tenancies', () => {
    const contracts = [
      { ...active, id: 'future', start_date: '2026-11-01' },
      { ...active, id: 'ended', end_date: '2026-10-15' },
      { ...active, id: 'notice', status: 'terminated', end_date: day },
      { ...active, id: 'draft', status: 'draft' },
      { ...active, id: 'expired', status: 'expired' },
    ];
    expect(contracts.map(row => contractPhase(row, day))).toEqual(['upcoming', 'history', 'current', 'drafts', 'history']);
    expect(currentContractsOn(contracts, day).map(row => row.id)).toEqual(['notice']);
    expect(occupancyOn({ id: 'u1', status: 'vacant' }, contracts, day)).toEqual({ status: 'occupied', tenant_id: 't1' });
    expect(occupancyOn({ id: 'u1', status: 'occupied' }, contracts, '2026-10-17')).toEqual({ status: 'vacant', tenant_id: null });
  });
  it('uses local calendar components, including near a UTC date boundary', () => {
    expect(localDay(new Date(2026, 9, 16, 0, 5))).toBe(day);
    expect(currentContractsOn([active, { ...active, id: 'parking', unit_id: 'parking' }], day)).toHaveLength(2);
  });
});
