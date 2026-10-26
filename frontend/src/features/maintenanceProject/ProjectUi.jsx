import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import PdfPreview from '../../components/PdfPreview';
import { CloseIcon } from '../../components/Icons';
import { useProjectText } from './text';
import './maintenanceProject.css';

export function Section({ title, actions, children, id }) {
  return (
    <section className="panel mp-section" aria-labelledby={id}>
      <div className="panel-header mp-section-header">
        <h2 id={id}>{title}</h2>
        {actions && <div className="mp-actions">{actions}</div>}
      </div>
      <div className="mp-section-body">{children}</div>
    </section>
  );
}

export function Empty({ children }) {
  return <p className="empty-text mp-empty">{children}</p>;
}

export function Pill({ tone = 'gray', children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Fact({ label, children }) {
  return (
    <div className="mp-fact">
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  );
}

// Closed details keep their descendants in the DOM, but only the summary can
// receive keyboard focus. Apply the same visibility rules to both trap ends.
function isKeyboardVisible(element) {
  if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  for (let node = element; node; node = node.parentElement) {
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    if (node.tagName === 'DETAILS' && !node.open) {
      const summary = [...node.children].find(child => child.tagName === 'SUMMARY');
      if (!summary?.contains(element)) return false;
    }
  }
  return true;
}

/** A modal shell: Escape and the backdrop close it, focus starts inside and stays there. */
export function Modal({ title, onClose, children, wide = false }) {
  const { tx } = useProjectText();
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });
  useEffect(() => {
    const previous = document.activeElement;
    const node = ref.current;
    const focusable = () => [...(node?.querySelectorAll(
      'button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])') || [])].filter(isKeyboardVisible);
    focusable()[0]?.focus();
    const onKey = event => {
      if (event.key === 'Escape') { event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    node?.addEventListener('keydown', onKey);
    return () => { node?.removeEventListener('keydown', onKey); previous?.focus?.(); };
  }, []);
  return createPortal(
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div ref={ref} className={`modal mp-modal${wide ? ' modal-wide' : ''}`} role="dialog" aria-modal="true"
        aria-label={title} onClick={event => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="btn-close" aria-label={tx.close} onClick={onClose}><CloseIcon size={18} /></button>
        </div>
        {children}
      </div>
    </div>, document.body
  );
}

/** Pages through a server lookup (search + "load more"); never loads a whole collection. */
export function PickerDialog({ title, load, renderItem, onPick, onClose, extra }) {
  const { tx } = useProjectText();
  const [q, setQ] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [skip, setSkip] = useState(0);
  const [nextSkip, setNextSkip] = useState(0);
  const [option, setOption] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    if (skip === 0) { setItems([]); setHasMore(false); }
    load({ q: submitted, skip, limit: 25, option }, { signal: controller.signal })
      .then(page => {
        if (controller.signal.aborted) return;
        const next = page?.next_skip ?? skip + 25;
        if (!Array.isArray(page?.items) || (page.has_more && (!Number.isFinite(next) || next <= skip))) {
          throw new Error('Die Auswahlliste konnte nicht vollständig gelesen werden.');
        }
        setItems(current => [...new Map([...(skip === 0 ? [] : current), ...page.items].map(item => [item.id, item])).values()]);
        setHasMore(Boolean(page.has_more));
        // A lookup may filter its page locally (already-linked documents, search).
        // Its server offset must advance by consumed rows, not by visible results.
        setNextSkip(next);
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Auswahl konnte nicht geladen werden.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load, submitted, skip, option, attempt]);

  const search = event => { event.preventDefault(); setSkip(0); setSubmitted(q.trim()); };
  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="modal-body">
        <form className="mp-search" onSubmit={search} role="search">
          <input type="search" value={q} onChange={event => setQ(event.target.value)} aria-label={tx.search}
            placeholder={tx.search} />
          <button type="submit" className="btn btn-secondary btn-sm">{tx.search}</button>
        </form>
        {extra && (
          <label className="mp-check">
            <input type="checkbox" checked={option} onChange={event => { setSkip(0); setOption(event.target.checked); }} />
            {extra}
          </label>
        )}
        {error && <div className="alert-error" role="alert">{error}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(value => value + 1)}>{tx.retry || 'Erneut laden'}</button></div>}
        {!loading && !error && items.length === 0 && <Empty>{tx.nothingFound}</Empty>}
        <ul className="mp-pick-list">
          {items.map(item => (
            <li key={item.id}>
              <div className="mp-pick-text">{renderItem(item)}</div>
              <button type="button" className="btn btn-primary btn-sm" disabled={loading || Boolean(error) || item.free === 0}
                onClick={() => onPick(item)}>{tx.choose}</button>
            </li>
          ))}
        </ul>
        {loading && <p className="text-muted" role="status">{tx.loading}</p>}
        {hasMore && !loading && !error && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSkip(nextSkip)}>{tx.loadMore}</button>
        )}
      </div>
    </Modal>
  );
}

/** The PDF bytes from the API (session-checked), shown through the app's own PDF viewer. */
export function PdfDialog({ title, load, onClose }) {
  const { tx } = useProjectText();
  const [url, setUrl] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    let created = null;
    load({ signal: controller.signal })
      .then(blob => {
        if (controller.signal.aborted) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch(failure => { if (failure?.name !== 'AbortError') setError(failure.message); });
    return () => { controller.abort(); if (created) URL.revokeObjectURL(created); };
  }, [load]);
  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="modal-body mp-pdf">
        {error && <div className="alert-error" role="alert">{error}</div>}
        {!error && !url && <p className="text-muted" role="status">{tx.loading}</p>}
        {url && <PdfPreview url={url} title={title} />}
      </div>
    </Modal>
  );
}
