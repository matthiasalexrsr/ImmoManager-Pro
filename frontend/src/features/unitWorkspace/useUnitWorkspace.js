import { useEffect, useState } from 'react';
import { api } from '../../api';

const text = value => typeof value === 'string' && value.length > 0;
const optionalMoney = value => value === null || (typeof value === 'number' && Number.isFinite(value));

function checked(value, unitId, pageSize) {
  if (!value || value.unit?.id !== unitId || !text(value.unit?.label)
      || !text(value.property?.id) || value.property.id !== value.unit.property_id || !text(value.property.name)
      || !['cold_rent', 'service_charge_advance', 'heating_advance'].every(key => optionalMoney(value.unit[key]))) {
    throw new Error('unit_workspace_invalid');
  }
  for (const name of ['active_contracts', 'contract_history', 'insurances']) {
    const page = value[name];
    if (!Array.isArray(page?.items) || page.items.length > pageSize || typeof page.has_more !== 'boolean'
        || (page.has_more ? !text(page.next_cursor) || !page.items.length : page.next_cursor !== null)) {
      throw new Error('unit_workspace_invalid');
    }
    const ids = new Set();
    for (const row of page.items) {
      if (!text(row?.id) || ids.has(row.id) || row.unit_id !== unitId || row.property_id !== value.property.id
          || (name === 'active_contracts' && row.status !== 'active')
          || (name !== 'insurances' && (!text(row.contract_number)
            || !(row.tenant_name === null || typeof row.tenant_name === 'string') || !optionalMoney(row.deposit_amount)))) {
        throw new Error('unit_workspace_invalid');
      }
      ids.add(row.id);
    }
  }
  return value;
}

export default function useUnitWorkspace(unitId, principal, cursors, generation) {
  const params = new URLSearchParams({ page_size: '25' });
  for (const [name, cursor] of Object.entries(cursors)) if (cursor) params.set(name, cursor);
  const query = params.toString();
  const source = JSON.stringify([unitId, principal, query, generation]);
  const [result, setResult] = useState({ source: null });
  useEffect(() => {
    if (!principal) return undefined;
    const controller = new AbortController();
    api.get(`/units/${encodeURIComponent(unitId)}/workspace?${query}`, { signal: controller.signal })
      .then(value => {
        if (!controller.signal.aborted) setResult({ source, data: checked(value, unitId, 25), error: null });
      }).catch(error => {
        if (!controller.signal.aborted) setResult({ source, data: null, error });
      });
    return () => controller.abort();
  }, [unitId, principal, query, source]);
  return result.source === source ? { ...result, loading: false } : { data: null, loading: true, error: null };
}
