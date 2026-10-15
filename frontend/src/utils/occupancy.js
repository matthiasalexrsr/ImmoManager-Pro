// Calendar-day equivalent of backend/domain/occupancy.unit_status_on.
export function occupancyOn(unit, contracts, day) {
  const tenancies = contracts.filter(contract => contract.unit_id === unit.id && contract.status !== 'draft');
  const current = tenancies.find(contract => ['active', 'terminated'].includes(contract.status)
    && contract.start_date <= day && (!contract.end_date || contract.end_date >= day));
  const stored = unit.status || 'vacant';
  return {
    status: current ? 'occupied' : stored === 'occupied' && tenancies.length ? 'vacant' : stored,
    tenant_id: current?.tenant_id || null,
  };
}

export function occupancyMapOn(units, contracts, day) {
  const byUnit = new Map();
  for (const contract of contracts) {
    if (!byUnit.has(contract.unit_id)) byUnit.set(contract.unit_id, []);
    byUnit.get(contract.unit_id).push(contract);
  }
  return Object.fromEntries(units.map(unit => [unit.id, occupancyOn(unit, byUnit.get(unit.id) || [], day)]));
}
