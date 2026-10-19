import { useId, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n';
import './workspace.css';

const LABELS = { body: 'Notiz', notes: 'Notizen', protocol_date: 'Übergabedatum', rooms: 'Räume', defects: 'Mängel', keys: 'Schlüssel', meters: 'Zähler',
  sender_name: 'Absender', sender_address: 'Absenderanschrift', recipient_name: 'Empfänger', recipient_address: 'Empfängeranschrift',
  subject: 'Betreff', salutation: 'Anrede', intro: 'Einleitung', closing: 'Schlussformel', signature: 'Unterschrift / Name',
  dwelling_address: 'Wohnungsanschrift', dwelling_label: 'Wohnung', housing_provider_name: 'Wohnungsgeber', housing_provider_address: 'Anschrift des Wohnungsgebers',
  owner_name: 'Eigentümer', actual_move_in_date: 'Tatsächlicher Einzug', issue_date: 'Ausstellungsdatum', issuer_name: 'Aussteller', issuer_role: 'Rolle',
  occupants: 'Einziehende Personen', owner_relation: 'Eigentümerbezug', tenant_signature: 'Unterschrift Mieter', landlord_signature: 'Unterschrift Vermieter',
  tenant_present: 'Mieter anwesend', landlord_present: 'Vermieter anwesend', overall_condition: 'Gesamtzustand', name: 'Name', condition: 'Zustand',
  description: 'Beschreibung', responsible: 'Zuständig', remedy: 'Maßnahme', due_date: 'Fälligkeit', key_type: 'Schlüsselart', label: 'Bezeichnung', handed_over: 'Übergeben', returned: 'Zurückgegeben',
  meter_type: 'Zählerart', meter_number: 'Zählernummer', unit: 'Maßeinheit', value: 'Wert', last_reading: 'Letzte Ablesung', amount: 'Betrag', booking_date: 'Buchungsdatum', payment_text: 'Buchungstext' };
// The editable controls follow the recovery notice in the shared form layouts.
// Do not search globally: another dialog, toolbar or hidden form must not get focus.
function nextEditableField(notice) {
  const query = 'input:not([type="hidden"]), select, textarea, [contenteditable="true"]';
  for (let sibling = notice?.nextElementSibling; sibling; sibling = sibling.nextElementSibling) {
    const elements = sibling.matches(query) ? [sibling] : [...sibling.querySelectorAll(query)];
    const field = elements.find(element => !element.matches(':disabled') && !element.readOnly
      && element.tabIndex !== -1 && !element.closest('[inert], [hidden], [aria-hidden="true"], [aria-disabled="true"]'));
    if (field) return field;
  }
  return null;
}
function DraftValues({ value }) {
  if (Array.isArray(value)) return <ol>{value.map((item, index) => <li key={index}><DraftValues value={item} /></li>)}</ol>;
  if (value && typeof value === 'object') return <dl className="draft-values">{Object.entries(value).filter(([key]) => key !== 'id' && key !== 'key' && !key.endsWith('_id') && !key.startsWith('_') && key !== 'correction_of').map(([key, item]) => <div key={key}><dt>{LABELS[key] || key.replaceAll('_', ' ')}</dt><dd><DraftValues value={item} /></dd></div>)}</dl>;
  return <span>{value === true ? 'Ja' : value === false ? 'Nein' : String(value ?? '—')}</span>;
}

export default function CustomDraftNotice({ draft, onRestore, currentValues, beforeRestore, locked = false }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const translated = t(key); return translated && translated !== key ? translated : fallback; };
  const confirmId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [compared, setCompared] = useState(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [focusHandoffTick, setFocusHandoffTick] = useState(0);
  const focusHandoffRef = useRef(false);
  const noticeRef = useRef(null);
  const discardRef = useRef(null);
  const keepRef = useRef(null);
  const busyRef = useRef(false);
  const generation = useRef(0);
  useLayoutEffect(() => {
    generation.current += 1; busyRef.current = false; focusHandoffRef.current = false;
    setBusy(false); setError(''); setCompared(null); setConfirmDiscard(false);
    return () => { generation.current += 1; };
  }, [draft.sessionKey]);
  useLayoutEffect(() => {
    if (confirmDiscard && !busy && !locked) keepRef.current?.focus();
  }, [confirmDiscard, busy, locked]);
  // A resumed or discarded draft may remove the active action button. Return
  // focus to the following editable form, once its recovered state is ready.
  useLayoutEffect(() => {
    if (!focusHandoffRef.current || busy || locked || draft.recovery || draft.status === 'changed'
      || draft.blocked || draft.ready === false) return;
    const notice = noticeRef.current;
    if (!notice) return;
    focusHandoffRef.current = false;
    const active = document.activeElement;
    // Do not override an explicit focus decision made by the calling form.
    if (active && active !== document.body && !notice.contains(active)) return;
    (nextEditableField(notice) || notice).focus();
  }, [focusHandoffTick, busy, locked, draft.recovery, draft.status, draft.blocked, draft.ready]);
  if (!draft.enabled) return null;
  const cancelDiscard = () => {
    if (busyRef.current || locked) return;
    setConfirmDiscard(false);
    discardRef.current?.focus();
  };
  const changed = draft.recovery?.source_state?.status === 'changed' || draft.status === 'changed';
  const recovery = draft.recovery || (changed ? { values: currentValues, source_state: { status: 'changed' } } : null);
  const run = async operation => {
    if (busyRef.current || locked) return;
    busyRef.current = true;
    const epoch = generation.current;
    const current = () => epoch === generation.current && (!draft.isCurrent || draft.isCurrent(draft.sessionKey));
    setBusy(true); setError('');
    try { await operation(current); } catch (failure) { if (current() && failure.name !== 'AbortError') {
      if (failure.statusCode === 409) setCompared(null);
      setError(failure.message);
    } }
    finally { if (current()) { busyRef.current = false; setBusy(false); } }
  };
  return <section ref={noticeRef} className="draft-recovery" aria-label="Entwurfssicherung" tabIndex={-1}
    onKeyDown={event => {
      if (!confirmDiscard) return;
      if (event.key === 'Escape' || (event.key === 'Enter' && (event.ctrlKey || event.metaKey))) {
        event.preventDefault(); event.stopPropagation();
        if (event.key === 'Escape') cancelDiscard();
      }
    }}>
    <span role="status">{draft.loading || draft.status === 'loading' ? 'Entwürfe werden geprüft …'
      : draft.recovery ? 'Ein gespeicherter Entwurf kann wiederaufgenommen werden.'
        : changed ? 'Die zugrunde liegende Akte wurde geändert. Bitte den aktuellen Stand prüfen.'
          : draft.status === 'saving' || draft.status === 'pending' ? 'Entwurf wird gesichert …'
            : draft.status === 'saved' ? 'Entwurf automatisch gesichert' : 'Eingaben werden automatisch als Entwurf gesichert.'}</span>
    {error && <p role="alert">{error}</p>}
    {draft.error && <p role="alert">{draft.error}<button type="button" className="btn btn-sm btn-secondary" onClick={draft.retry}>Erneut versuchen</button></p>}
    {recovery && <>
      <details><summary>Entwurfsinhalt prüfen</summary><DraftValues value={recovery.values} /></details>
      {compared && <details open><summary>Aktueller Stand zum Vergleich</summary><DraftValues value={compared} /></details>}
      <div className="workspace-actions">
        {recovery.source_state?.status !== 'deleted' && <button type="button" className="btn btn-secondary" disabled={busy || locked || confirmDiscard} onClick={() => run(async current => {
          if (changed && !compared) {
            const fresh = draft.compare ? await draft.compare(beforeRestore) : await beforeRestore?.();
            if (current()) setCompared(fresh || currentValues || {}); return;
          }
          await draft.recover(recovery.values);
          if (current()) {
            onRestore?.(recovery.values);
            focusHandoffRef.current = true;
            setFocusHandoffTick(tick => tick + 1);
          }
        })}>{changed && !compared ? 'Aktuellen Stand vergleichen' : 'Entwurf übernehmen'}</button>}
        <button ref={discardRef} type="button" className="btn btn-ghost" disabled={busy || locked}
          aria-expanded={confirmDiscard} aria-controls={confirmDiscard ? confirmId : undefined}
          onClick={() => setConfirmDiscard(true)}>{tr('ui.form.discardDraft', 'Entwurf verwerfen')}</button>
      </div>
      {confirmDiscard && <div id={confirmId} className="draft-discard-confirm" role="group"
        aria-label={tr('ui.form.confirmRecoveredDiscard', 'Entwurf verwerfen bestätigen')}>
        <p role="alert">{tr('ui.form.recoveredDiscardWarning', 'Wiedergefundenen Entwurf endgültig verwerfen? Die ungespeicherten Eingaben gehen verloren.')}</p>
        <div className="workspace-actions">
          <button ref={keepRef} type="button" className="btn btn-secondary" disabled={busy || locked}
            onClick={cancelDiscard}>{tr('ui.form.keepRecoveredDraft', 'Entwurf behalten')}</button>
          <button type="button" className="btn btn-danger" disabled={busy || locked}
            onClick={() => run(async current => {
              await draft.clear();
              if (current()) {
                setConfirmDiscard(false);
                // Keep focus accessible even if the server recovery snapshot has
                // not disappeared yet; transfer to the editor when it does.
                noticeRef.current?.focus();
                focusHandoffRef.current = true;
                setFocusHandoffTick(tick => tick + 1);
              }
            })}>{tr('ui.form.discardRecoveredDraft', 'Endgültig verwerfen')}</button>
        </div>
      </div>}
    </>}
  </section>;
}
