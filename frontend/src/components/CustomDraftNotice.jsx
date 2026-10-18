import { useId, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n';
import './workspace.css';

const LABELS = { body: 'Notiz', notes: 'Notizen', protocol_date: 'Übergabedatum', rooms: 'Räume', defects: 'Mängel', keys: 'Schlüssel', meters: 'Zähler',
  dwelling_address: 'Wohnungsanschrift', dwelling_label: 'Wohnung', housing_provider_name: 'Wohnungsgeber', housing_provider_address: 'Anschrift des Wohnungsgebers',
  owner_name: 'Eigentümer', actual_move_in_date: 'Tatsächlicher Einzug', issue_date: 'Ausstellungsdatum', issuer_name: 'Aussteller', issuer_role: 'Rolle',
  occupants: 'Einziehende Personen', owner_relation: 'Eigentümerbezug', tenant_signature: 'Unterschrift Mieter', landlord_signature: 'Unterschrift Vermieter',
  tenant_present: 'Mieter anwesend', landlord_present: 'Vermieter anwesend', overall_condition: 'Gesamtzustand', name: 'Name', condition: 'Zustand',
  description: 'Beschreibung', responsible: 'Zuständig', remedy: 'Maßnahme', due_date: 'Fälligkeit', key_type: 'Schlüsselart', label: 'Bezeichnung', handed_over: 'Übergeben', returned: 'Zurückgegeben',
  meter_type: 'Zählerart', meter_number: 'Zählernummer', unit: 'Maßeinheit', value: 'Wert', last_reading: 'Letzte Ablesung', amount: 'Betrag', booking_date: 'Buchungsdatum', payment_text: 'Buchungstext' };
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
  const noticeRef = useRef(null);
  const discardRef = useRef(null);
  const keepRef = useRef(null);
  const busyRef = useRef(false);
  const generation = useRef(0);
  useLayoutEffect(() => {
    generation.current += 1; busyRef.current = false;
    setBusy(false); setError(''); setCompared(null); setConfirmDiscard(false);
    return () => { generation.current += 1; };
  }, [draft.sessionKey]);
  useLayoutEffect(() => {
    if (confirmDiscard && !busy && !locked) keepRef.current?.focus();
  }, [confirmDiscard, busy, locked]);
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
          if (current()) onRestore(recovery.values);
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
              if (current()) { setConfirmDiscard(false); noticeRef.current?.focus(); }
            })}>{tr('ui.form.discardRecoveredDraft', 'Endgültig verwerfen')}</button>
        </div>
      </div>}
    </>}
  </section>;
}
