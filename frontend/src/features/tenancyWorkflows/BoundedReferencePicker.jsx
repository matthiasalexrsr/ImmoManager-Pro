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
  getLabel = item => item.name || item.title || item.label || item.id,
  getDescription = () => '',
  isSelectable = () => true,
  pageSize = PAGE_SIZE,
  sourceKey = '',
  disabled = false,
  required = false,
}) {
  const id = useId();
  const [items, setItems] = useState([]);
  const [offset, setOffset] = useState(0);
  const [cursor, setCursor] = useState(null);
  const [hasMore, setHasMore] = useState(true);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const request = useRef(null);
  const generation = useRef(0);
  const loadPageRef = useRef(loadPage);
  const keyRef = useRef(getKey);
  const selectedRef = useRef(selectedItem);
  loadPageRef.current = loadPage;
  keyRef.current = getKey;
  selectedRef.current = selectedItem;
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  const load = useCallback(async ({ nextOffset = 0, nextCursor = null, replace = false } = {}) => {
    if (disabled || typeof loadPageRef.current !== 'function') return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const run = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const response = await loadPageRef.current({
        offset: nextOffset,
        cursor: nextCursor,
        limit: pageSize,
        signal: controller.signal,
      });
      if (controller.signal.aborted || run !== generation.current) return;
      const page = Array.isArray(response) ? response : response?.items;
      if (!Array.isArray(page)) throw new Error('invalid_reference_page');
      const returnedCursor = Array.isArray(response)
        ? null
        : response.next_cursor ?? response.nextCursor ?? null;
      const returnedHasMore = Array.isArray(response)
        ? page.length === pageSize
        : response.has_more ?? response.hasMore ?? Boolean(returnedCursor);
      setItems(current => {
        const merged = replace ? page : [...current, ...page];
        const unique = new Map();
        for (const item of merged) unique.set(String(keyRef.current(item)), item);
        if (selectedRef.current) {
          unique.set(String(keyRef.current(selectedRef.current)), selectedRef.current);
        }
        return [...unique.values()];
      });
      setOffset(nextOffset + page.length);
      setCursor(returnedCursor);
      setHasMore(Boolean(returnedHasMore));
    } catch (failure) {
      if (!controller.signal.aborted && run === generation.current) setError(failure.message);
    } finally {
      if (!controller.signal.aborted && run === generation.current) setLoading(false);
    }
  }, [disabled, pageSize]);

  useEffect(() => {
    generation.current += 1;
    request.current?.abort();
    setItems(selectedRef.current ? [selectedRef.current] : []);
    setOffset(0);
    setCursor(null);
    setHasMore(true);
    setQuery('');
    setError(null);
    if (!disabled) load({ nextOffset: 0, nextCursor: null, replace: true });
    return () => request.current?.abort();
  }, [disabled, load, sourceKey]);

  useEffect(() => {
    if (!selectedItem) return;
    setItems(current => {
      const key = String(keyRef.current(selectedItem));
      return current.some(item => String(keyRef.current(item)) === key)
        ? current
        : [selectedItem, ...current];
    });
  }, [selectedItem]);

  const selected = useMemo(
    () => items.find(item => String(getKey(item)) === String(value))
      || (selectedItem && String(getKey(selectedItem)) === String(value) ? selectedItem : null),
    [getKey, items, selectedItem, value],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase(locale);
    if (!needle) return items;
    return items.filter(item => `${getLabel(item)} ${getDescription(item)}`.toLocaleLowerCase(locale).includes(needle));
  }, [getDescription, getLabel, items, locale, query]);

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

      <div className="workflow-reference__search">
        <Search size={16} aria-hidden="true" />
        <input
          id={`${id}-search`}
          type="search"
          value={query}
          disabled={disabled}
          placeholder={tr('search')}
          onChange={event => setQuery(event.target.value)}
        />
      </div>

      {error && <div className="workflow-inline-error" role="alert">{error}</div>}
      <div className="workflow-reference__results" role="listbox" aria-labelledby={`${id}-label`}>
        {filtered.map(item => {
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
        {!loading && filtered.length === 0 && <p className="workflow-muted">{tr('noOptions')}</p>}
      </div>

      <div className="workflow-reference__footer">
        {loading && <span role="status">{tr('loading')}</span>}
        <button type="button" className="btn btn-secondary btn-sm"
          disabled={disabled || loading || !hasMore}
          onClick={() => load({ nextOffset: offset, nextCursor: cursor })}>
          {tr('loadMore')}
        </button>
      </div>
    </section>
  );
}
