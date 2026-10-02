// This routing map mirrors backend/permissions.py. The server supplies the
// actual grants in UserRead.write_permissions; unknown resources are admin.
export const RESOURCE_CAPABILITY = {
  portfolios: 'portfolio', properties: 'portfolio', units: 'portfolio',
  tenants: 'rental', contracts: 'rental', 'contract-wizard': 'rental',
  accounts: 'finance', bookings: 'finance', receivables: 'finance', invoices: 'finance', deposits: 'finance',
  budgets: 'finance', 'tax-rates': 'finance', reports: 'finance', 'rent-charges': 'finance',
  'rent-adjustments': 'finance', categories: 'finance', insurances: 'finance', billing: 'billing',
  maintenance: 'operations', tasks: 'operations', calendar: 'operations', escalation: 'operations',
  meters: 'operations', 'handover-protocols': 'operations', 'tasks-status': 'operations',
  documents: 'documents', files: 'documents', photos: 'documents',
  listings: 'marketing', leads: 'marketing', viewings: 'marketing',
  messages: 'communication', contacts: 'communication', notifications: 'communication', 'notification-templates': 'communication', 'communication-center': 'communication',
};

const all = ['administration', 'portfolio', 'rental', 'finance', 'billing', 'operations', 'documents', 'marketing', 'communication'];
const legacyRoleGrants = {
  eigentuemer: all, verwalter: all,
  buchhaltung: ['finance', 'billing', 'documents', 'communication'],
  techniker: ['operations', 'documents', 'communication'], readonly: [],
};

export function writePermissions(user) {
  if (!user) return [];
  // A supplied empty list is authoritative, including for an owner. The role
  // fallback supports the legacy UserRead shape; it never grants unknown roles.
  return Array.isArray(user.write_permissions) ? user.write_permissions : legacyRoleGrants[user.role] || [];
}

export function resourceCapability(endpoint) {
  const resource = String(endpoint || '').replace(/^\/?(?:api\/)?v1\//, '').replace(/^\//, '').split(/[/?]/)[0];
  return RESOURCE_CAPABILITY[resource] || 'administration';
}

export function mayWrite(user, endpoint) {
  return writePermissions(user).includes(resourceCapability(endpoint));
}

export function authMayWrite(auth, endpoint) {
  if (typeof auth?.canWrite === 'function') return auth.canWrite(endpoint);
  return mayWrite(auth?.user || (auth?.role ? { role: auth.role } : null), endpoint);
}
