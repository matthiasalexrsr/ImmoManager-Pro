import { useCallback, useEffect, useId, useRef, useState } from 'react';
import WorkflowTechnicalDetails from './WorkflowTechnicalDetails';
import { workflowText } from './workflowCopy';
import { PAGE_SIZE } from './tenancyWorkflowModel';
import './TenancyWorkflows.css';

export default function DocumentVersionPicker({
  documentId,
  locale = 'de-DE',
  value = null,
  onChange,
  loadPage,
  disabled = false,
}) {
  const id = useId();
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const request = useRef(null);
  const generation = useRef(0);
  const change = useRef(onChange);
  const loadPageRef = useRef(loadPage);
  change.current = onChange;
  loadPageRef.current = loadPage;
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  const load = useCallback(async (before = null, append = false) => {
    if (!documentId || typeof loadPageRef.current !== 'function' || disabled) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const run = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await loadPageRef.current(documentId, { before, limit: PAGE_SIZE, signal: controller.signal });
      if (controller.signal.aborted || run !== generation.current) return;
      if (!result || !Array.isArray(result.items)) throw new Error('invalid_document_version_page');
      setItems(current => append ? [...current, ...result.items] : result.items);
      setCursor(result.next_before ?? null);
      setHasMore(result.next_before != null);
    } catch (failure) {
      if (!controller.signal.aborted && run === generation.current) setError(failure.message);
    } finally {
      if (!controller.signal.aborted && run === generation.current) setLoading(false);
    }
  }, [disabled, documentId]);

  useEffect(() => {
    generation.current += 1;
    request.current?.abort();
    setItems([]);
    setCursor(null);
    setHasMore(false);
    setError(null);
    change.current?.(null);
    if (documentId && !disabled) load(null, false);
    return () => request.current?.abort();
  }, [disabled, documentId, load]);

  const selectedVersion = items.find(item => String(item.id) === String(value)) || null;

  return (
    <section className="workflow-version-picker" aria-labelledby={`${id}-title`}>
      <h4 id={`${id}-title`}>{tr('selectVersion')}</h4>
      {error && <div className="workflow-inline-error" role="alert">{error}</div>}
      <div className="workflow-version-picker__list" role="radiogroup" aria-labelledby={`${id}-title`}>
        {items.map(item => (
          <label key={item.id} className={String(value) === String(item.id) ? 'is-selected' : ''}>
            <input type="radio" name={`${id}-version`} value={item.id}
              checked={String(value) === String(item.id)} disabled={disabled}
              onChange={() => onChange?.(item)} />
            <span>
              <strong>v{item.number} · {item.filename}</strong>
              <small>{item.created_at ? new Date(item.created_at).toLocaleString(locale) : '—'}</small>
            </span>
          </label>
        ))}
        {!loading && items.length === 0 && <p className="workflow-muted">{tr('noOptions')}</p>}
      </div>
      {selectedVersion && (
        <WorkflowTechnicalDetails locale={locale} rows={[
          { label: tr('technicalIdentifier'), value: selectedVersion.id },
          { label: 'SHA-256', value: selectedVersion.sha256 },
        ]} />
      )}
      <div className="workflow-reference__footer">
        {loading && <span role="status">{tr('loading')}</span>}
        <button type="button" className="btn btn-secondary btn-sm"
          disabled={disabled || loading || !hasMore} onClick={() => load(cursor, true)}>
          {tr('loadMore')}
        </button>
      </div>
    </section>
  );
}
