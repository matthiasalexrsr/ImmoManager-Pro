// Record snapshots belong to the object/form that read them, never a global ID
// cache. Symbols survive object spreads but never enter JSON request bodies.
export const EDIT_REVISION = Symbol.for('ImmoManager.originalEditRevision.v1');

const collections = new Set([
  'portfolios', 'properties', 'units', 'accounts', 'categories', 'tenants', 'contracts',
  'bookings', 'receivables', 'invoices', 'maintenance', 'documents', 'tasks', 'calendar',
  'listings', 'leads', 'viewings', 'deposits', 'tax-rates', 'budgets', 'rent-adjustments',
  'handover-protocols', 'handover-protocols/meter-readings', 'insurances', 'contacts', 'meters',
  'meters/readings', 'rent-charges', 'notifications', 'notifications/templates', 'messages/threads',
  'escalation/rules', 'billing/periods', 'billing/allocation-keys', 'billing/cost-items', 'billing/statements',
]);

export function revisionResource(path) {
  const suffix = path.replace(/^\/api\/v1\//, '/').split('?')[0].replace(/^\/|\/$/g, '');
  const parts = suffix.split('/');
  if ([3, 4].includes(parts.length) && parts[0] === 'handover-protocols' && parts[2] === 'meter-readings') {
    return { collection: 'handover-protocols/meter-readings', id: parts[3] || null };
  }
  if (parts.length === 3 && parts[0] === 'meters' && (parts[2] === 'readings' || parts[1] === 'readings' && parts[2] === 'all')) {
    return { collection: 'meters/readings', id: null };
  }
  for (const collection of [...collections].sort((a, b) => b.length - a.length)) {
    if (suffix === collection) return { collection, id: null };
    if (suffix.startsWith(`${collection}/`) && !suffix.slice(collection.length + 1).includes('/')) {
      return { collection, id: decodeURIComponent(suffix.slice(collection.length + 1)) };
    }
  }
  return null;
}

export function snapshotRevision(record) {
  if (record?.[EDIT_REVISION]) return record[EDIT_REVISION];
  if (record?.id && typeof record.updated_at === 'string') {
    return Object.freeze({ id: record.id, updatedAt: record.updated_at, source: Object.freeze({ ...record }) });
  }
  return null;
}

export function revisionSource(payload, fallback) {
  return snapshotRevision(payload)?.source || fallback;
}

export function bindEditRevision(payload, revision) {
  if (revision) Object.defineProperty(payload, EDIT_REVISION, { value: revision, enumerable: true, configurable: true });
  return payload;
}

export function annotateRevisions(data, path, responseEtag) {
  const resource = revisionResource(path);
  if (!resource) return data;
  const records = Array.isArray(data) ? data : [data];
  for (const record of records) {
    if (!record?.id || typeof record.updated_at !== 'string') continue;
    const revision = Object.freeze({ collection: resource.collection, id: record.id, updatedAt: record.updated_at,
      path: resource.id ? path.split('?')[0] : null, etag: !Array.isArray(data) ? responseEtag : null,
      source: Object.freeze({ ...record }) });
    Object.defineProperty(record, EDIT_REVISION, { value: revision, configurable: true });
  }
  return data;
}

export function revisionOptions(record) {
  const revision = snapshotRevision(record);
  return revision ? { ifMatch: revision } : {};
}

export function conditionalHeaders(path, payload, options = {}) {
  const revision = options.ifMatch || payload?.[EDIT_REVISION];
  const resource = revisionResource(path);
  if (!revision || !resource?.id) return {};
  if (revision.id !== resource.id || revision.collection && revision.collection !== resource.collection) {
    throw new Error('Der Bearbeitungsstand gehört zu einem anderen Datensatz.');
  }
  // Preserve all six server microsecond digits; Date.toISOString() would lose
  // precision and make an unchanged record falsely conflict.
  const etag = revision.etag || `"immo-v1:${encodeURIComponent(resource.collection)}:${encodeURIComponent(revision.id)}:${revision.updatedAt}"`;
  return { 'If-Match': etag };
}
