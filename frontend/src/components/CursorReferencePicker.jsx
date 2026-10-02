import { useEffect, useId, useState } from 'react';

export default function CursorReferencePicker({
  label, value, onChange, loadPage, getLabel, placeholder = 'Auswählen',
  disabled = false, required = false, emptyLabel = 'Keine', pageSize = 25,
}) {
  const id = useId();
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    setCursor(null);
    setHasMore(true);
    setError('');
    setLoading(true);
    Promise.resolve(loadPage({ after: null, limit: pageSize, signal: controller.signal }))
      .then(page => {
        if (controller.signal.aborted) return;
        setItems(Array.isArray(page?.items) ? page.items : []);
        setCursor(page?.next_cursor || null);
        setHasMore(Boolean(page?.has_more));
      })
      .catch(failure => {
        if (!controller.signal.aborted) setError(failure.message || 'Auswahl konnte nicht geladen werden.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loadPage, pageSize]);

  const loadMore = async () => {
    if (!hasMore || loading) return;
    setLoading(true); setError('');
    try {
      const page = await loadPage({ after: cursor, limit: pageSize });
      const next = Array.isArray(page?.items) ? page.items : [];
      setItems(current => {
        const ids = new Set(current.map(item => item.id));
        return [...current, ...next.filter(item => !ids.has(item.id))];
      });
      setCursor(page?.next_cursor || null);
      setHasMore(Boolean(page?.has_more));
    } catch (failure) {
      setError(failure.message || 'Weitere Einträge konnten nicht geladen werden.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="workflow-field">
      <label htmlFor={id}>{label}{required ? ' *' : ''}</label>
      <div className="workflow-reference-row">
        <select id={id} value={value || ''} onChange={event => onChange(event.target.value || null)}
          disabled={disabled || loading && items.length === 0} required={required}>
          {!required && <option value="">{emptyLabel}</option>}
          {required && !value && <option value="">{placeholder}</option>}
          {items.map(item => <option key={item.id} value={item.id}>{getLabel(item)}</option>)}
        </select>
        {hasMore && <button type="button" className="btn btn-secondary btn-sm" onClick={loadMore} disabled={loading}>
          {loading ? '…' : 'Mehr'}
        </button>}
      </div>
      {error && <p className="workflow-field-error" role="alert">{error}</p>}
    </div>
  );
}
