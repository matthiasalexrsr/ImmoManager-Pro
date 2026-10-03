export const families = ['tasks', 'notifications', 'expiring_contracts'];
export const cursorNames = { tasks: 'tasks_after', notifications: 'notifications_after', expiring_contracts: 'contracts_after' };
export const freshTrails = () => Object.fromEntries(families.map(name => [name, [null]]));
const object = value => value && typeof value === 'object' && !Array.isArray(value);
export const text = value => typeof value === 'string' && value.length > 0;
const optional = value => value === null || typeof value === 'string';
export const count = value => Number.isSafeInteger(value) && value >= 0;
export function day(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
const fail = () => { throw new Error('dashboard_summary_invalid'); };
const statKeys = ['portfolio_count', 'property_count', 'unit_count', 'tenant_count', 'active_contracts', 'account_count',
  'open_maintenance', 'overdue_maintenance', 'document_count', 'open_tasks', 'unread_notifications',
  'open_rent_charges', 'overdue_rent_charges', 'open_receivables', 'overdue_receivables', 'draft_billing_periods',
  'occupied_units', 'vacant_units', 'reserved_units', 'billing_preflight_periods_checked',
  'billing_preflight_blockers', 'billing_preflight_warnings'];

export function summaryQuery(query, trails) {
  const parameters = new URLSearchParams({ preview_limit: String(query.limit) });
  if (query.asOf) parameters.set('as_of', query.asOf);
  for (const family of families) {
    const after = trails[family].at(-1);
    if (after) parameters.set(cursorNames[family], after);
  }
  return `/dashboard/stats?${parameters}`;
}

export function checkedSummary(value, query, trails) {
  if (!object(value) || value.basis !== 'dashboard-status-v1' || !day(value.as_of)
    || (query.asOf && value.as_of !== query.asOf) || !statKeys.every(key => count(value[key]))) fail();
  const occupancy = value.occupancy;
  if (!object(occupancy) || occupancy.basis !== 'stored_unit_status'
    || !['total', 'occupied', 'rented', 'vacant', 'reserved', 'other'].every(key => count(occupancy[key]))
    || occupancy.total !== value.unit_count || occupancy.rented > occupancy.occupied
    || occupancy.occupied + occupancy.vacant + occupancy.reserved + occupancy.other !== occupancy.total
    || occupancy.occupied !== value.occupied_units + occupancy.rented
    || occupancy.vacant !== value.vacant_units || occupancy.reserved !== value.reserved_units) fail();
  const presence = value.billing_presence;
  if (!object(presence) || presence.basis !== 'basic_presence_checks' || presence.complete_preflight !== false
    || !['periods_checked', 'blockers', 'warnings'].every(key => count(presence[key]))
    || presence.blockers > presence.periods_checked
    || ['periods_checked', 'blockers', 'warnings'].some(key => presence[key] !== value[`billing_preflight_${key}`])) fail();
  if (!object(value.work_hints)) fail();
  const hints = {};
  for (const family of families) {
    const page = value.work_hints[family];
    if (!object(page) || !count(page.total) || !Array.isArray(page.items) || page.items.length > query.limit
      || page.items.length > page.total || typeof page.has_more !== 'boolean' || !text(page.source_url)
      || (page.has_more ? !text(page.next_after) || !page.items.length : page.next_after !== null)
      || (!trails[family].at(-1) && page.total > 0 && !page.items.length)
      || (family === 'tasks' && page.total !== value.open_tasks)
      || (family === 'notifications' && page.total !== value.unread_notifications)) fail();
    const ids = new Set();
    const items = page.items.map(row => {
      if (!object(row) || !text(row.id) || ids.has(row.id)) fail();
      ids.add(row.id);
      if (family === 'tasks') {
        if (typeof row.title !== 'string' || typeof row.priority !== 'string' || !(row.due_date === null || day(row.due_date))) fail();
        return { id: row.id, title: row.title, priority: row.priority, due_date: row.due_date };
      }
      if (family === 'notifications') {
        if (typeof row.title !== 'string' || typeof row.severity !== 'string' || !optional(row.entity_type) || !optional(row.entity_id)) fail();
        return { id: row.id, title: row.title, severity: row.severity, entity_type: row.entity_type, entity_id: row.entity_id };
      }
      if (typeof row.contract_number !== 'string' || !day(row.end_date) || !count(row.days_remaining)
        || row.days_remaining > 90 || (Date.parse(`${row.end_date}T00:00:00Z`) - Date.parse(`${value.as_of}T00:00:00Z`)) / 86400000 !== row.days_remaining) fail();
      return { id: row.id, contract_number: row.contract_number, end_date: row.end_date, days_remaining: row.days_remaining };
    });
    // Never retain provider descriptions or unknown private payloads in this overview.
    hints[family] = { total: page.total, items, has_more: page.has_more, next_after: page.next_after, source_url: page.source_url };
  }
  return { ...Object.fromEntries(statKeys.map(key => [key, value[key]])), as_of: value.as_of, basis: value.basis,
    occupancy: Object.fromEntries(['total', 'occupied', 'rented', 'vacant', 'reserved', 'other', 'basis'].map(key => [key, occupancy[key]])),
    billing_presence: Object.fromEntries(['periods_checked', 'blockers', 'warnings', 'basis', 'complete_preflight'].map(key => [key, presence[key]])), work_hints: hints };
}

export const accessDenied = error => [401, 403].includes(error?.statusCode);
export function hintTarget(row) {
  const routes = { property: '/properties', unit: '/units', tenant: '/tenants', receivable: '/receivables',
    rent_charge: '/rent-charges', maintenance: '/maintenance', invoice: '/invoices', document: '/documents', billing_period: '/statements' };
  if (!row.entity_id || !routes[row.entity_type]) return null;
  const route = routes[row.entity_type];
  return ['property', 'unit'].includes(row.entity_type) ? `${route}/${encodeURIComponent(row.entity_id)}` : route;
}
