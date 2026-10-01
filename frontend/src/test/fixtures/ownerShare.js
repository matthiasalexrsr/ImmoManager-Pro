export function ownerPeriod(id = 'period') {
  return { id, status: 'draft', owner_cost_share: {
    total_amount: '120.00', recoverable_vacancy_amount: '50.00', non_recoverable_amount: '70.00',
    property_cost_total: '170.00', tenant_cost_total: '50.00',
    vacant_unit_days: { vacant: 31 }, policy: 'property_units_occupied_days',
    line_items: [
      { cost_item_id: 'cost-vacancy', description: 'Heating vacancy', allocated_amount: 50, unit_id: 'vacant', reason: 'vacancy' },
      { cost_item_id: 'cost-owner', description: 'Owner-only cost', allocated_amount: 70, unit_id: null, reason: 'non_recoverable' },
    ],
  } };
}
