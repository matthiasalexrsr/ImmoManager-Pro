export function localDay(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

// A notice of termination does not end occupation before its actual end date.
export function contractPhase(contract, day = localDay()) {
  if (contract.status === 'draft') return 'drafts';
  if (!['active', 'terminated'].includes(contract.status) || (contract.end_date && contract.end_date < day)) return 'history';
  if (contract.start_date > day) return 'upcoming';
  return 'current';
}

export function currentContractsOn(contracts, day = localDay()) {
  return contracts.filter(contract => contractPhase(contract, day) === 'current');
}

// Calendar-day equivalent of backend/domain/occupancy.unit_status_on.
export function occupancyOn(unit, contracts, day) {
  const tenancies = contracts.filter(contract => contract.unit_id === unit.id && contract.status !== 'draft');
  const current = currentContractsOn(tenancies, day)[0];
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
