import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { mayWrite } from '../../utils/permissions';
import { entityHref } from '../../utils/entityLinks';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';
import CustomDraftNotice from '../../components/CustomDraftNotice';
import PdfPreview from '../../components/PdfPreview';
import UnsavedNavigationGuard, { NavigationScopeNotice } from '../../components/UnsavedNavigationGuard';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { checkLetterPreview, LETTER_FIELDS, REQUIRED_LETTER_FIELDS, letterData, letterPdfHash, letterSignature, statementLetterService } from './statementLetterApi';
import './statementLetterDialog.css';

const FIELDS = LETTER_FIELDS.map(key => ({ key }));
const LABELS = { sender_name: 'Absender', sender_address: 'Absenderanschrift', recipient_name: 'Empfänger', recipient_address: 'Empfängeranschrift', issue_date: 'Briefdatum', subject: 'Betreff', salutation: 'Anrede', intro: 'Einleitung', closing: 'Schlussformel', signature: 'Unterschrift / Name' };
const MULTILINE = new Set(['sender_address', 'recipient_address', 'intro', 'closing']);
const empty = () => ({ context: null, form: null, baseline: '', loading: true, error: '', conflict: false, denied: false, preview: null, published: null });
const privateFailure = error => [401, 403].includes(error?.statusCode) || error?.code === 'SESSION_CHANGED';

export default function StatementLetterDialog({ statementId, onClose, onPublished, service = statementLetterService }) {
  const auth = useAuth();
  const user = auth?.user;
  const write = auth?.write ?? null;
  const binding = JSON.stringify([user?.id || '', user?.role || '', write && [...write].sort(), statementId]);
  const allowed = Boolean(user?.id && user.role !== 'readonly' && mayWrite(write, '/billing/periods') && mayWrite(write, '/documents'));
  return <StatementLetterSession key={binding} statementId={statementId} onClose={onClose} onPublished={onPublished}
    service={service} allowed={allowed} authenticated={Boolean(user?.id)} />;
}

function StatementLetterSession({ statementId, onClose, onPublished, service, allowed, authenticated }) {
  const id = useId();
  const dialog = useRef(null);
  const leaveDialog = useRef(null);
  const alive = useRef(false);
  const controllers = useRef(new Set());
  const objectUrl = useRef(null);
  const sequence = useRef(0);
  const pending = useRef(null);
  const busyRef = useRef(null);
  const holdRef = useRef(false);
  const leaveRef = useRef(null);
  const [state, setState] = useState(empty);
  const currentState = useRef(state);
  currentState.current = state;
  const [busy, setBusy] = useState(null);
  const [uncertain, setUncertain] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [leave, setLeave] = useState(null);
  const [notice, setNotice] = useState('');
  const draft = useEntityFormDraft({ context: 'billing-statement-letter', kind: 'utility_statement', id: statementId,
    fields: FIELDS, enabled: allowed && Boolean(state.context) && !state.denied && service === statementLetterService });
  const dirty = Boolean(state.form && letterSignature(state.form) !== state.baseline);
  const draftLocked = draft.enabled && (draft.loading || !draft.ready || Boolean(draft.recovery) || draft.status === 'changed');
  const locked = Boolean(pending.current) || (busy && busy !== 'preview') || draftLocked;
  const canPublish = allowed && state.context?.can_publish === true;
  const change = update => setState(previous => {
    const next = typeof update === 'function' ? update(previous) : update;
    currentState.current = next;
    return next;
  });
  const setWorking = value => { busyRef.current = value; setBusy(value); };
  const revoke = () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); objectUrl.current = null; };
  const abort = () => { for (const controller of controllers.current) controller.abort(); controllers.current.clear(); };
  const start = () => { const controller = new AbortController(); controllers.current.add(controller); return controller; };
  const active = controller => alive.current && !controller.signal.aborted;
  const invalidate = () => { sequence.current += 1; revoke(); setConfirmed(false); change(old => ({ ...old, preview: null })); };
  const failure = error => {
    if (privateFailure(error)) {
      abort(); revoke(); pending.current = null; setUncertain(false); setWorking(null); setConfirmed(false);
      leaveRef.current?.reset?.(); leaveRef.current = null; setLeave(null);
      change({ ...empty(), loading: false, denied: true, error: 'Der Zugriff ist nicht mehr erlaubt. Die privaten Briefdaten wurden ausgeblendet.' });
      return;
    }
    if ([409, 412].includes(error?.statusCode)) {
      invalidate(); change(old => ({ ...old, conflict: true, error: error.message }));
    } else change(old => ({ ...old, error: error?.message || 'Der Brief konnte nicht verarbeitet werden.' }));
  };

  const load = async (preserve = false) => {
    if (pending.current || busyRef.current === 'clear') return;
    abort(); invalidate();
    const controller = start();
    setWorking('reload');
    change(old => ({ ...old, loading: true, error: '' }));
    try {
      const context = await service.loadContext(statementId, { signal: controller.signal });
      if (!active(controller)) return;
      if (typeof context?.source_revision !== 'string' || !context.defaults || !Array.isArray(context.originals)) throw new Error('Der Briefkontext ist unvollständig. Bitte erneut laden.');
      change(old => {
        const form = preserve && old.form ? old.form : letterData(context.defaults);
        return { ...old, context, form, baseline: preserve && old.form ? old.baseline : letterSignature(form), loading: false, conflict: false, error: '', preview: null };
      });
    } catch (error) { if (active(controller)) { failure(error); change(old => ({ ...old, loading: false })); } }
    finally { controllers.current.delete(controller); if (active(controller)) setWorking(null); }
  };

  useLayoutEffect(() => {
    alive.current = true;
    return () => { alive.current = false; abort(); revoke(); };
  }, []);
  useEffect(() => { if (authenticated) void load(); else change({ ...empty(), loading: false, denied: true });
    return abort;
    // The keyed session owns a single statement/user/permissions/service snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pendingNavigation = useCallback(() => Boolean(pending.current || busyRef.current === 'publish' || busyRef.current === 'clear'), []);
  const requestClose = request => {
    if (pendingNavigation()) { setNotice('Die Archivierung oder Entwurfsbereinigung muss zuerst eindeutig abgeschlossen werden.'); return; }
    // Reads can be cancelled before asking about disposal. Their late finally
    // handlers must not unlock a subsequent, still-pending draft deletion.
    if (busyRef.current) { abort(); sequence.current += 1; setWorking(null); change(old => ({ ...old, loading: false })); }
    if (dirty || request?.proceed) { leaveRef.current = request || { proceed: () => { onClose(); return true; } }; setLeave(leaveRef.current); }
    else onClose();
  };
  useModalDialog(dialog, () => {
    if (leaveRef.current) { if (busyRef.current !== 'clear') { leaveRef.current.reset?.(); leaveRef.current = null; setLeave(null); } return; }
    requestClose();
  });
  const keep = () => { if (busyRef.current === 'clear') return; leaveRef.current?.reset?.(); leaveRef.current = null; setLeave(null); };
  useModalDialog(leaveDialog, keep, Boolean(leave));
  const discard = async () => {
    if (pendingNavigation()) return;
    const request = leaveRef.current;
    if (!request) return;
    holdRef.current = true; setWorking('clear'); setNotice('');
    try {
      await draft.clear();
      if (!alive.current) return;
      setWorking(null); holdRef.current = false;
      // A router request may be refreshed while a shared draft is removed.
      if (request.proceed?.() !== false) { leaveRef.current = null; setLeave(null); }
    } catch (error) { if (alive.current) failure(error); }
    finally { holdRef.current = false; if (alive.current) setWorking(null); }
  };
  const updateField = (key, value) => {
    if (locked || !state.form) return;
    if (busyRef.current === 'preview') { abort(); setWorking(null); }
    invalidate();
    const form = { ...currentState.current.form, [key]: value };
    change(old => ({ ...old, form, published: null, error: '' })); draft.stage(form);
  };
  const payload = () => {
    const data = letterData(currentState.current.form);
    if (REQUIRED_LETTER_FIELDS.some(key => !data[key]) || !/^\d{4}-\d{2}-\d{2}$/.test(data.issue_date)) {
      change(old => ({ ...old, error: 'Bitte Absender, Empfänger, Anschriften, Briefdatum, Betreff und Anrede vollständig ausfüllen.' })); return null;
    }
    return { source_revision: currentState.current.context.source_revision, data };
  };
  const preview = async event => {
    event?.preventDefault();
    if (locked || busyRef.current || state.conflict || !state.context) return;
    const body = payload(); if (!body) return;
    invalidate(); const ticket = sequence.current; const controller = start(); setWorking('preview');
    change(old => ({ ...old, error: '' }));
    try {
      const review = checkLetterPreview(await service.preview(statementId, body, { signal: controller.signal }), body);
      if (!active(controller) || ticket !== sequence.current) return;
      const blob = await service.previewPdf(statementId, body, { signal: controller.signal });
      const hash = await letterPdfHash(blob);
      if (!active(controller) || ticket !== sequence.current) return;
      if (hash !== review.pdf_sha256) throw new Error('Die PDF-Datei stimmt nicht mit der geprüften Vorschau überein. Bitte neu erstellen.');
      revoke(); objectUrl.current = URL.createObjectURL(blob);
      change(old => ({ ...old, preview: { ...review, url: objectUrl.current, payload: body }, error: '' }));
    } catch (error) { if (active(controller) && ticket === sequence.current) failure(error); }
    finally { controllers.current.delete(controller); if (active(controller)) setWorking(null); }
  };
  const publish = async () => {
    if (busyRef.current || !canPublish) return;
    if (!pending.current) {
      if (locked || !confirmed || !state.preview || state.preview.review.draft || state.conflict) return;
      pending.current = { ...state.preview.payload, review_hash: state.preview.review_hash, idempotency_key: crypto.randomUUID() };
    }
    const command = pending.current;
    const expectedHash = state.preview?.pdf_sha256;
    const controller = start(); setWorking('publish'); setNotice(''); change(old => ({ ...old, error: '' }));
    try {
      const result = await service.publish(statementId, command, { signal: controller.signal });
      if (!active(controller)) return;
      if (!result?.document_id || !result?.version_id || result.review_hash !== command.review_hash || result.pdf_sha256 !== expectedHash) {
        throw new Error('Die Archivierung konnte nicht eindeutig bestätigt werden. Bitte denselben Auftrag erneut prüfen.');
      }
      pending.current = null; setUncertain(false);
      change(old => ({ ...old, baseline: letterSignature(old.form), published: result,
        context: { ...old.context, originals: [result, ...old.context.originals.filter(item => item.version_id !== result.version_id)] } }));
      setConfirmed(false);
      try { await draft.clear({ completed: true }); } catch (error) {
        if (active(controller) && privateFailure(error)) { failure(error); return; }
        if (active(controller)) setNotice('Das Original ist archiviert. Die Entwurfsbereinigung wird beim nächsten Öffnen erneut geprüft.');
      }
      if (active(controller)) { try { onPublished?.(result); } catch { setNotice('Das Original ist archiviert. Bitte die Abrechnungsliste erneut laden.'); } }
    } catch (error) {
      if (!active(controller)) return;
      if (privateFailure(error)) failure(error);
      else if ([400, 404, 409, 412, 422].includes(error?.statusCode)) { pending.current = null; setUncertain(false); failure(error); }
      else { setUncertain(true); change(old => ({ ...old, error: 'Die Serverantwort zur Archivierung ist unklar. Die Eingaben bleiben gesperrt. Wiederholen prüft denselben Auftrag und erzeugt kein zweites Original.' })); }
    } finally { controllers.current.delete(controller); if (active(controller)) setWorking(null); }
  };
  const download = async record => {
    if (busyRef.current || pending.current) return;
    const controller = start(); setWorking('download');
    try {
      const blob = await service.downloadOriginal(record, { signal: controller.signal });
      if (!active(controller)) return;
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'Betriebskostenabrechnung.pdf'; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (active(controller)) failure(error); }
    finally { controllers.current.delete(controller); if (active(controller)) setWorking(null); }
  };

  return createPortal(<div className="modal-overlay statement-letter-overlay" onClick={event => { if (event.target === event.currentTarget) requestClose(); }}>
    <section className="statement-letter-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <UnsavedNavigationGuard when={dirty || Boolean(pending.current) || busy === 'clear' || busy === 'publish'} pending={pendingNavigation} holdRef={holdRef} label="Abrechnungsbrief"
        onBlocked={request => { if (request.cancelled) keep(); else if (request.pending) setNotice('Ein laufender oder ungeklärter Auftrag muss zuerst abgeschlossen werden.'); else requestClose(request); }} />
      <header className="statement-letter-header"><div><h2 id={`${id}-title`}>Abrechnungsbrief</h2><p>Brief prüfen und als Original in den Dokumenten archivieren.</p></div><button type="button" className="btn-close" aria-label="Briefdialog schließen" onClick={() => requestClose()}>×</button></header>
      <div className="statement-letter-body">
        {state.loading && <p role="status">Briefdaten werden geladen …</p>}
        {state.error && <p className="statement-letter-error" role="alert">{state.error}</p>}
        {notice && <p role="status">{notice}</p>}
        {state.conflict && <div className="statement-letter-warning"><p>Die Abrechnung oder ihre Briefdaten wurden geändert. Laden Sie den aktuellen Stand; Ihre Briefeingaben bleiben erhalten. Anschließend ist eine neue PDF-Prüfung nötig.</p><button type="button" className="btn btn-secondary" disabled={Boolean(busy) || uncertain} onClick={() => load(true)}>Aktuellen Stand laden, Eingaben behalten</button></div>}
        {!state.loading && !state.context && !state.denied && <button type="button" className="btn btn-secondary" onClick={() => load()}>Erneut laden</button>}
        {state.context && state.form && <>
          {!state.context.can_publish && <p className="statement-letter-warning">Diese Fassung kann hier nicht als Original archiviert werden. Dafür müssen eine finalisierte Mieterabrechnung und die nötige Berechtigung vorliegen.</p>}
          {state.context.warnings?.length > 0 && <ul className="statement-letter-warning">{state.context.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
          <div className="statement-letter-columns">
            <form id={`${id}-form`} className="statement-letter-fields" onSubmit={preview}>
              <CustomDraftNotice draft={draft} currentValues={state.form} locked={Boolean(pending.current) || Boolean(busy)}
                beforeRestore={async () => { const fresh = await service.loadContext(statementId); if (!alive.current) throw new DOMException('Gewechselt', 'AbortError'); invalidate(); change(old => ({ ...old, context: fresh, conflict: false })); return letterData(fresh.defaults); }}
                onRestore={values => { invalidate(); change(old => ({ ...old, form: letterData(values), published: null })); }} />
              <fieldset disabled={Boolean(locked) || state.loading || state.denied}><legend>Brieffelder</legend>
                {LETTER_FIELDS.map(key => <div key={key} className={`statement-letter-field${MULTILINE.has(key) || ['subject', 'salutation'].includes(key) ? ' statement-letter-wide' : ''}`}><label htmlFor={`${id}-${key}`}>{LABELS[key]}{REQUIRED_LETTER_FIELDS.includes(key) ? ' *' : ''}</label>
                  {MULTILINE.has(key) ? <textarea id={`${id}-${key}`} rows={key === 'intro' ? 4 : 2} required={REQUIRED_LETTER_FIELDS.includes(key)} value={state.form[key]} onChange={event => updateField(key, event.target.value)} />
                    : <input id={`${id}-${key}`} type={key === 'issue_date' ? 'date' : 'text'} required={REQUIRED_LETTER_FIELDS.includes(key)} value={state.form[key]} onChange={event => updateField(key, event.target.value)} />}
                </div>)}
              </fieldset>
              <button type="submit" className="btn btn-secondary" disabled={Boolean(locked) || Boolean(busy) || state.conflict}>{busy === 'preview' ? 'PDF wird erstellt …' : 'PDF-Vorschau erstellen'}</button>
            </form>
            <section className="statement-letter-preview" aria-label="Briefvorschau"><h3>{state.published ? 'Archiviertes Original – geprüfte Fassung' : state.preview?.review.draft ? 'Entwurf – nicht archiviert' : 'PDF-Vorschau – noch nicht archiviert'}</h3>
              {state.preview ? <PdfPreview key={state.preview.url} url={state.preview.url} title="Abrechnungsbrief" /> : <p>Nach Änderungen am Brief bitte eine neue PDF-Vorschau erstellen.</p>}
            </section>
          </div>
          {state.published && <div className="statement-letter-success" role="status">Das Original wurde archiviert. <Link to={entityHref('document', state.published.document_id)}>Dokument öffnen</Link><p>Der Brief wurde nicht versendet. Die weitere Kommunikation kann vom Dokument aus vorbereitet werden.</p></div>}
          <section className="statement-letter-history" aria-label="Originalhistorie"><h3>Archivierte Originale</h3>{!state.context.originals.length ? <p>Für diese Abrechnung liegt noch kein archivierter Brief vor.</p> : <ul>{state.context.originals.map((record, index) => <li key={record.version_id || index}><span>{record.created_at ? new Date(record.created_at).toLocaleString('de-DE') : 'Archiviertes Original'}</span><Link to={entityHref('document', record.document_id)}>Dokument öffnen</Link><button type="button" className="btn btn-sm btn-secondary" disabled={Boolean(busy) || uncertain} onClick={() => download(record)}>Original herunterladen</button></li>)}</ul>}</section>
        </>}
      </div>
      <footer className="statement-letter-footer">
        <button type="button" className="btn btn-secondary" onClick={() => requestClose()} disabled={pendingNavigation()}>Schließen</button>
        {uncertain ? <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={publish}>Archivierung erneut prüfen</button> : state.context && <div><label className="statement-letter-confirm"><input type="checkbox" checked={confirmed} disabled={!state.preview || !canPublish || Boolean(locked) || Boolean(busy) || state.conflict || state.preview?.review.draft} onChange={event => setConfirmed(event.target.checked)} />Ich habe die aktuelle PDF geprüft und möchte sie als Original archivieren.</label><button type="button" className="btn btn-primary" disabled={!confirmed || !state.preview || !canPublish || Boolean(locked) || Boolean(busy) || state.conflict || Boolean(state.published)} onClick={publish}>{busy === 'publish' ? 'Original wird archiviert …' : 'Als Original archivieren'}</button></div>}
      </footer>
      {leave && <div ref={leaveDialog} className="statement-letter-leave" role="alertdialog" aria-modal="true" aria-labelledby={`${id}-leave`} tabIndex={-1}><h3 id={`${id}-leave`}>Briefeingaben verwerfen?</h3><p>Die ungespeicherten Eingaben dieses Briefs werden verworfen.</p>{leave.scopeLabels?.length > 1 && <NavigationScopeNotice labels={leave.scopeLabels} />}
        <div><button type="button" className="btn btn-secondary" disabled={busy === 'clear'} onClick={keep}>Weiter bearbeiten</button><button type="button" className="btn btn-danger" disabled={busy === 'clear'} onClick={discard}>{busy === 'clear' ? 'Entwurf wird entfernt …' : leave.scopeLabels?.length > 1 ? 'Alle genannten Eingaben verwerfen' : 'Eingaben verwerfen'}</button></div></div>}
    </section>
  </div>, document.body);
}
