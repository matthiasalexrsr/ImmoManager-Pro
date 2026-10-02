import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { workflowText } from './workflowCopy';
import { PAGE_SIZE } from './tenancyWorkflowModel';
import './TenancyWorkflows.css';

export default function BoundedReferencePicker({
  label,
  locale = 'de-DE',
  value = null,
  selectedItem = null,
  onChange,
  loadPage,
  getKey = item => item.id,
  getLabel = item => item.name || item.title || item.label || item.full_name || item.id,
  getDescription = () => '',
  isSelectable = () => true,
  pageSize = PAGE_SIZE,
  sourceKey = '',
  searchEnabled = true,
  disabled = false,
  required = false,
}) {
  const id = useId();
  const [items, setItems] = useState([]);
  const [serverSelected, setServerSelected] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [hasMore, setHasMore] = useState(true);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const request = useRef(null);
  const generation = useRef(0);
  const loadPageRef = useRef(loadPage);
  const keyRef = useRef(getKey);
  const valueRef = useRef(value);
  loadPageRef.current = loadPage;
  keyRef.current = getKey;
  valueRef.current = value;
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  const load = useCallback(async ({
    nextCursor = null,
    replace = false,
    search = '',
  } = {}) => {
    if (disabled || typeof loadPageRef.current !== 'function') return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const run = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const response = await loadPageRef.current({
        cursor: nextCursor,
        search,
        selectedId: valueRef.current || null,
        limit: pageSize,
        signal: controller.signal,
      });
      if (controller.signal.aborted || run !== generation.current) return;
      if (!response || typeof response !== 'object' || Array.isArray(response)
          || !Array.isArray(response.items)) {
        throw new Error('invalid_reference_page');
      }
      const returnedCursor = response.next_cursor ?? null;
      const returnedHasMore = response.has_more === true;
      if ((returnedHasMore && typeof returnedCursor !== 'string')
          || (!returnedHasMore && returnedCursor != null)) {
        throw new Error('invalid_reference_page');
      }
      setItems(current => {
        const merged = replace ? response.items : [...current, ...response.items];
        const unique = new Map();
        for (const item of merged) unique.set(String(keyRef.current(item)), item);
        return [...unique.values()];
      });
      setServerSelected(response.selected && typeof response.selected === 'object'
        ? response.selected
        : null);
      setCursor(returnedCursor);
      setHasMore(returnedHasMore);
    } catch (failure) {
      if (!controller.signal.aborted && run === generation.current) setError(failure.message);
    } finally {
      if (!controller.signal.aborted && run === generation.current) setLoading(false);
    }
  }, [disabled, pageSize]);

  useEffect(() => {
    generation.current += 1;
    request.current?.abort();
    setItems([]);
    setServerSelected(null);
    setCursor(null);
    setHasMore(true);
    setQuery('');
    setError(null);
    if (!disabled) load({ nextCursor: null, replace: true, search: '' });
    return () => request.current?.abort();
  }, [disabled, load, sourceKey]);

  useEffect(() => {
    if (selectedItem) setServerSelected(selectedItem);
  }, [selectedItem]);

  const selected = useMemo(() => {
    const fromItems = items.find(item => String(getKey(item)) === String(value));
    if (fromItems) return fromItems;
    if (selectedItem && String(getKey(selectedItem)) === String(value)) return selectedItem;
    if (serverSelected && String(getKey(serverSelected)) === String(value)) return serverSelected;
    return null;
  }, [getKey, items, selectedItem, serverSelected, value]);

  const changeSearch = event => {
    const next = event.target.value;
    setQuery(next);
    setCursor(null);
    setHasMore(true);
    load({ nextCursor: null, replace: true, search: next });
  };

  return (
    <section className="workflow-reference" aria-labelledby={`${id}-label`}>
      <div className="workflow-reference__heading">
        <label id={`${id}-label`} htmlFor={`${id}-search`}>{label}{required ? ' *' : ''}</label>
        {selected && (
          <button type="button" className="workflow-reference__clear" disabled={disabled} onClick={() => onChange?.(null)}>
            {tr('clear')}
          </button>
        )}
      </div>

      {selected && (
        <div className="workflow-reference__selected" role="status">
          <span>{tr('selected')}</span>
          <strong>{getLabel(selected)}</strong>
          {getDescription(selected) && <small>{getDescription(selected)}</small>}
        </div>
      )}

      {searchEnabled && (
        <div className="workflow-reference__search">
          <Search size={16} aria-hidden="true" />
          <input
            id={`${id}-search`}
            type="search"
            value={query}
            disabled={disabled}
            placeholder={tr('search')}
            onChange={changeSearch}
          />
        </div>
      )}

      {error && <div className="workflow-inline-error" role="alert">{error}</div>}
      <div className="workflow-reference__results" role="listbox" aria-labelledby={`${id}-label`}>
        {items.map(item => {
          const key = String(getKey(item));
          const active = String(value) === key;
          const selectable = isSelectable(item);
          return (
            <button
              key={key}
              type="button"
              role="option"
              aria-selected={active}
              className={active ? 'is-selected' : ''}
              disabled={disabled || !selectable}
              aria-disabled={!selectable}
              onClick={() => onChange?.(item)}
            >
              <strong>{getLabel(item)}</strong>
              {getDescription(item) && <small>{getDescription(item)}</small>}
            </button>
          );
        })}
        {!loading && items.length === 0 && <p className="workflow-muted">{tr('noOptions')}</p>}
      </div>

      <div className="workflow-reference__footer">
        {loading && <span role="status">{tr('loading')}</span>}
        <button type="button" className="btn btn-secondary btn-sm"
          disabled={disabled || loading || !hasMore}
          onClick={() => load({ nextCursor: cursor, search: query })}>
          {tr('loadMore')}
        </button>
      </div>
    </section>
  );
}
