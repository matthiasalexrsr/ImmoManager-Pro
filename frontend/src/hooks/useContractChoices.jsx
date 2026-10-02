import { useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';

const LIMIT = 25;
const choice = value => value && typeof value.id === 'string' && value.id && typeof value.label === 'string';

export default function useContractChoices(kind, selectedId, label, propertyId = '') {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [paging, setPaging] = useState({ owner: null, offset: 0 });
  const [generation, setGeneration] = useState(0);
  const owner = `${kind}:${propertyId}:${search}`;
  const offset = paging.owner === owner ? paging.offset : 0;
  const params = new URLSearchParams({ search, offset: String(offset), limit: String(LIMIT) });
  if (selectedId) params.set('selected_id', selectedId);
  if (propertyId) params.set('property_id', propertyId);
  const query = params.toString();
  const sourceKey = `${kind}:${query}:${generation}`;
  const [result, setResult] = useState({ sourceKey: null });
  const enabled = kind !== 'units' || Boolean(propertyId);
  const state = result.sourceKey === sourceKey ? result : { items: [], selected: null, loading: enabled };
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const value = await api.get(`/contract-wizard/choices/${kind}?${query}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (!Array.isArray(value?.items) || value.items.length > LIMIT || !value.items.every(choice)
            || !(value.selected === null || (choice(value.selected) && value.selected.id === selectedId))
            || typeof value.has_more !== 'boolean' || value.offset !== offset || value.limit !== LIMIT) {
          throw new Error('contractWorkspace.invalidResult');
        }
        // Existing archived tenants remain valid historical relationships.
        // Read only this exact selected tenant through its current scoped API;
        // do not make archived tenants generic new-contract choices.
        let selectedChoice = value.selected;
        if (kind === 'tenants' && selectedId && !selectedChoice && !value.items.some(item => item.id === selectedId)) {
          const selected = await api.get(`/tenants/${encodeURIComponent(selectedId)}`, { signal: controller.signal });
          if (selected?.id !== selectedId || typeof selected.full_name !== 'string' || selected.archived !== true) {
            throw new Error('contractWorkspace.missingReference');
          }
          selectedChoice = { id: selected.id, label: selected.full_name, archived: true };
        }
        if (selectedId && !selectedChoice && !value.items.some(item => item.id === selectedId)) throw new Error('contractWorkspace.missingReference');
        if (!controller.signal.aborted) setResult({ ...value, selected: selectedChoice, sourceKey, loading: false });
      } catch (error) {
        if (!controller.signal.aborted) setResult({ sourceKey, items: [], selected: null, loading: false, error });
      }
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [enabled, kind, offset, query, selectedId, sourceKey]);
  const items = [...(state.selected && !state.items.some(item => item.id === state.selected.id) ? [state.selected] : []), ...state.items];
  const disabled = !enabled || state.loading || Boolean(state.error);
  return {
    options: items.map(item => ({ value: item.id, label: item.archived ? `${item.label} · ${t('contractWorkspace.archivedTenant')}` : item.label })), disabled,
    hint: <span className="contract-choice-hint">
      <label>{t('contractWorkspace.findReference', { label })}<input type="search" name={`lookup_contract_${kind}`}
        value={search} disabled={!enabled}
        onChange={event => { setSearch(event.target.value); setPaging({ owner: null, offset: 0 }); }} /></label>
      {!enabled && <span>{t('contractWorkspace.chooseProperty')}</span>}
      {state.loading && <span role="status">{t('ui.table.loading')}</span>}
      {state.error && <span role="alert">{state.error.message.startsWith('contractWorkspace.') ? t(state.error.message) : state.error.message}
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => setGeneration(value => value + 1)}>{t('ui.buttons.retry')}</button></span>}
      {enabled && (offset > 0 || state.has_more) && <span className="contract-choice-pages">
        <button type="button" className="btn btn-sm btn-secondary" disabled={!offset || disabled}
          aria-label={t('contractWorkspace.previousChoices', { label })}
          onClick={() => setPaging({ owner, offset: Math.max(0, offset - LIMIT) })}>{t('ui.table.previousPage')}</button>
        <button type="button" className="btn btn-sm btn-secondary" disabled={!state.has_more || disabled}
          aria-label={t('contractWorkspace.nextChoices', { label })}
          onClick={() => setPaging({ owner, offset: offset + LIMIT })}>{t('ui.table.nextPage')}</button>
      </span>}
    </span>,
  };
}
