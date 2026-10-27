// Which list a page edits, and whether the signed-in role may change it (see backend/permissions.py).
const ROUTE_AREAS = {
  statements: '/billing/periods',
  'allocation-keys': '/billing/allocation-keys',
  'escalation-rules': '/escalation/rules',
  'notification-templates': '/notifications/templates',
  'rent-overview': '/rent-charges',
  'unit-overview': '/units',
};

export function areaForRoute(pathname) {
  const first = (pathname || '/').split('/')[1] || '';
  return ROUTE_AREAS[first] || `/${first}`;
}

// write: null = everything, [] = nothing, else path prefixes (a leading "^" marks a regular expression)
export function mayWrite(write, path) {
  if (write === null) return true;
  if (!Array.isArray(write)) return false;
  return write.some(p => (p.startsWith('^') ? new RegExp(p).test(path)
    : path === p || path.startsWith(`${p.replace(/\/$/, '')}/`)));
}
