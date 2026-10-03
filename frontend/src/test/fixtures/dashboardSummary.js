export function summaryFixture() {
  return { portfolio_count: 1, property_count: 2, unit_count: 100005, tenant_count: 3, active_contracts: 3, account_count: 0,
    open_maintenance: 1, overdue_maintenance: 0, document_count: 4, open_tasks: 6, unread_notifications: 1,
    open_rent_charges: 2, overdue_rent_charges: 1, open_receivables: 3, overdue_receivables: 1, draft_billing_periods: 2,
    occupied_units: 2, vacant_units: 100000, reserved_units: 1,
    billing_preflight_periods_checked: 2, billing_preflight_blockers: 1, billing_preflight_warnings: 3,
    as_of: '2026-10-03', basis: 'dashboard-status-v1',
    occupancy: { total: 100005, occupied: 3, rented: 1, vacant: 100000, reserved: 1, other: 1, basis: 'stored_unit_status' },
    billing_presence: { periods_checked: 2, blockers: 1, warnings: 3, basis: 'basic_presence_checks', complete_preflight: false },
    work_hints: {
      tasks: { total: 6, items: [{ id: 'task-first', title: 'First task', due_date: null, priority: 'custom' }], has_more: true, next_after: 'actual-opaque-task-token', source_url: '/tasks?status=open' },
      notifications: { total: 1, items: [{ id: 'notice', title: 'Notice', severity: 'custom', entity_type: 'unit', entity_id: 'unit-id' }], has_more: false, next_after: null, source_url: '/notifications?status=unread' },
      expiring_contracts: { total: 1, items: [{ id: 'contract', contract_number: 'MV-1', end_date: '2026-10-03', days_remaining: 0 }], has_more: false, next_after: null, source_url: '/contracts' },
    } };
}
