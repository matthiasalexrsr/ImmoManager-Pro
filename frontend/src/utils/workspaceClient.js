import { api } from '../api';

const path = (resource, id) => `/workspace/${resource}${id == null ? '' : `/${String(id).split('/').map(encodeURIComponent).join('/')}`}`;
export const workspace = {
  command: () => crypto.randomUUID(),
  list: (resource, query = {}, options) => {
    const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value != null && value !== ''));
    return api.get(`${path(resource)}${params.size ? `?${params}` : ''}`, options);
  },
  get: (resource, id, options, query = {}) => {
    const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value != null && value !== ''));
    return api.get(`${path(resource, id)}${params.size ? `?${params}` : ''}`, options);
  },
  put: (resource, id, data, options) => api.put(path(resource, id), data, options),
  rebase: (id, data) => api.post(`${path('drafts', id)}/rebase`, data),
  remove: (resource, id, data, options = {}) => api.del(path(resource, id), { ...options, data }),
  touch: (kind, entity_id) => api.post('/workspace/recents/events', {
    kind, entity_id, idempotency_key: crypto.randomUUID(),
  }),
};

export const FORM_KINDS = {
  portfolios: 'portfolio', properties: 'property', units: 'unit', tenants: 'tenant', contracts: 'contract',
  accounts: 'account', bookings: 'booking', invoices: 'invoice', maintenance: 'maintenance', tasks: 'task',
  documents: 'document', contacts: 'contact', meters: 'meter', readings: 'reading', categories: 'category',
  deposits: 'deposit', insurances: 'insurance', 'service-contracts': 'service_contract', leads: 'lead',
  listings: 'listing', viewings: 'viewing', budgets: 'budget', 'rent-adjustments': 'rent_adjustment',
  'rent-charges': 'rent_charge', 'tax-rates': 'tax_rate', 'allocation-keys': 'allocation_key',
  receivables: 'receivable', calendar: 'calendar', 'handover-protocols': 'handover_protocol',
  'escalation-rules': 'escalation_rule', 'notification-templates': 'notification_template',
  'billing/periods': 'billing_period', 'billing/cost-items': 'cost_item', 'billing/allocation-keys': 'allocation_key',
};
export function formContext(pathname) {
  const context = pathname.split('/').filter(Boolean)[0];
  return FORM_KINDS[context] ? context : null;
}
