import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CloseIcon } from '../../components/Icons';
import { retentionService } from './retentionApi';

/** Deleting a document whose retention period runs: explains why it stays, and lets an
 *  owner or manager delete it anyway with a reason that goes to the audit journal. */
export default function RetentionLockDialog({ document, retention, canOverride, onClose, onDeleted, service = retentionService }) {
  const id = useId();
  const ref = useRef(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  useEffect(() => {
    const previous = globalThis.document.activeElement;
    ref.current?.querySelector('textarea, button')?.focus();
    const onKey = event => { if (event.key === 'Escape') close.current(); };
    globalThis.document.addEventListener('keydown', onKey);
    return () => { globalThis.document.removeEventListener('keydown', onKey); previous?.focus?.(); };
  }, []);

  const submit = async event => {
    event.preventDefault();
    if (busy) return;
    if (reason.trim().length < 10) { setError('Bitte den Grund in mindestens 10 Zeichen angeben.'); return; }
    setBusy(true); setError('');
    try { await service.remove(document.id, reason.trim()); onDeleted(); }
    catch (problem) { setError(problem.message || 'Das Dokument konnte nicht gelöscht werden.'); }
    finally { setBusy(false); }
  };

  return createPortal(
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div ref={ref} className="modal retention-lock-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`}
        onClick={event => event.stopPropagation()}>
        <div className="modal-header">
          <h3 id={`${id}-title`}>Aufbewahrungspflicht</h3>
          <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">
          <p><strong>„{document.title}“</strong> kann noch nicht gelöscht werden.</p>
          <p>{retention.text}</p>
          {retention.basis && <p className="text-muted">Grundlage: {retention.basis}{retention.chosen ? ' · im Dokument so eingestuft' : ' · nach Dokumenttyp'}</p>}
          <p className="text-muted">Ist die Einstufung falsch, ändern Sie im Dokument die Angabe „Aufbewahrung“.</p>
          {canOverride ? <form onSubmit={submit}>
            <label htmlFor={`${id}-reason`}>Trotzdem löschen, weil …</label>
            <textarea id={`${id}-reason`} rows={3} maxLength={500} value={reason} onChange={event => setReason(event.target.value)}
              placeholder="z. B. versehentlich doppelt abgelegt; das Original liegt als Dokument „Rechnung R-17“ vor" />
            <small className="text-muted">Der Grund wird mit Ihrem Namen im Änderungsprotokoll festgehalten.</small>
            {error && <p role="alert" className="alert alert-error">{error}</p>}
            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={onClose}>Behalten</button>
              <button type="submit" className="btn btn-danger" disabled={busy}>{busy ? 'Wird gelöscht …' : 'Trotzdem löschen'}</button>
            </div>
          </form> : <>
            <p className="text-muted">Löschen trotz Aufbewahrungsfrist dürfen nur Eigentümer und Verwaltung, mit Begründung.</p>
            <div className="modal-footer"><button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button></div>
          </>}
        </div>
      </div>
    </div>, globalThis.document.body);
}
