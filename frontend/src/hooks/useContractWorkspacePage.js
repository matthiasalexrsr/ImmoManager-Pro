import { useEffect, useState } from 'react';
import { api } from '../api';
import { bindEditRevision } from '../editRevision';

const text = value => typeof value === 'string' && value.length > 0;
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const optionalText = value => value === null || typeof value === 'string';
const etagId = value => encodeURIComponent(value).replace(/[!'()*]/g, char => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);

export default function useContractWorkspacePage(filters, cursor, pageSize, generation) {
  const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '' && value != null));
  params.set('page_size', String(pageSize));
  if (cursor) params.set('cursor', cursor);
  const query = params.toString();
  const sourceKey = `${query}:${generation}`;
  const [result, setResult] = useState({ sourceKey: null });
  useEffect(() => {
    const controller = new AbortController();
    setResult({ sourceKey, items: [], loading: true });
    api.get(`/contracts/workspace/page?${query}`, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value?.items) || value.items.length > pageSize || typeof value.has_more !== 'boolean'
          || !date(value.reference_date)
          || (value.has_more ? !text(value.next_cursor) || !value.items.length : value.next_cursor !== null)) {
        throw new Error('contractWorkspace.invalidResult');
      }
      const ids = new Set();
      const items = value.items.map(row => {
        if (!row || !['id', 'contract_number', 'property_id', 'unit_id', 'tenant_id', 'updated_at'].every(key => text(row[key]))
            || !['active', 'terminated', 'expired', 'draft'].includes(row.status) || !date(row.start_date)
            || !(row.end_date === null || date(row.end_date))
            || !['property_name', 'unit_label', 'tenant_name'].every(key => optionalText(row[key]))
            || !(row.unit_cold_rent === null || (typeof row.unit_cold_rent === 'number' && Number.isFinite(row.unit_cold_rent)))
            || !(row.deposit_amount === null || (typeof row.deposit_amount === 'number' && Number.isFinite(row.deposit_amount)))
            || typeof row.edit_etag !== 'string' || !row.edit_etag.startsWith(`"immo-v1:contracts:${etagId(row.id)}:`)
            || !/^"immo-v1:contracts:[^"]+"$/.test(row.edit_etag)
            || ids.has(row.id)) throw new Error('contractWorkspace.invalidResult');
        ids.add(row.id);
        const record = { ...row };
        return bindEditRevision(record, Object.freeze({ collection: 'contracts', id: row.id,
          updatedAt: row.updated_at, etag: row.edit_etag, path: `/contracts/${encodeURIComponent(row.id)}`,
          source: Object.freeze({ ...row }) }));
      });
      setResult({ sourceKey, items, loading: false, error: null, hasMore: value.has_more,
        nextCursor: value.next_cursor, referenceDate: value.reference_date });
    }).catch(error => {
      if (!controller.signal.aborted) setResult({ sourceKey, items: [], loading: false, error });
    });
    return () => controller.abort();
  }, [query, sourceKey, pageSize]);
  return result.sourceKey === sourceKey ? result : { items: [], loading: true };
}
