import { useLayoutEffect, useRef, useState } from 'react';
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [compared, setCompared] = useState(null);
  const generation = useRef(0);
  useLayoutEffect(() => {
    generation.current += 1; setBusy(false); setError(''); setCompared(null);
    return () => { generation.current += 1; };
  }, [draft.sessionKey]);
  if (!draft.enabled) return null;
  const changed = draft.recovery?.source_state?.status === 'changed' || draft.status === 'changed';
  const recovery = draft.recovery || (changed ? { values: currentValues, source_state: { status: 'changed' } } : null);
  const run = async operation => {
    if (busy) return;
    const epoch = generation.current;
    const current = () => epoch === generation.current && (!draft.isCurrent || draft.isCurrent(draft.sessionKey));
    setBusy(true); setError('');
    try { await operation(current); } catch (failure) { if (current() && failure.name !== 'AbortError') {
      if (failure.statusCode === 409) setCompared(null);
      setError(failure.message);
    } }
    finally { if (current()) setBusy(false); }
  };
  return <section className="draft-recovery" aria-label="Entwurfssicherung">
    <span role="status">{draft.loading || draft.status === 'loading' ? 'Entwürfe werden geprüft …'
      : draft.recovery ? 'Ein gespeicherter Entwurf kann wiederaufgenommen werden.'
        : changed ? 'Die zugrunde liegende Akte wurde geändert. Bitte den aktuellen Stand prüfen.'
          : draft.status === 'saving' || draft.status === 'pending' ? 'Entwurf wird gesichert …'
            : draft.status === 'saved' ? 'Entwurf automatisch gesichert' : 'Eingaben werden automatisch als Entwurf gesichert.'}</span>
    {(error || draft.error) && <p role="alert">{error || draft.error}<button type="button" className="btn btn-sm btn-secondary" onClick={draft.retry}>Erneut versuchen</button></p>}
    {recovery && <>
      <details><summary>Entwurfsinhalt prüfen</summary><DraftValues value={recovery.values} /></details>
      {compared && <details open><summary>Aktueller Stand zum Vergleich</summary><DraftValues value={compared} /></details>}
      <div className="workspace-actions">
        {recovery.source_state?.status !== 'deleted' && <button type="button" className="btn btn-secondary" disabled={busy || locked} onClick={() => run(async current => {
          if (changed && !compared) {
            const fresh = draft.compare ? await draft.compare(beforeRestore) : await beforeRestore?.();
            if (current()) setCompared(fresh || currentValues || {}); return;
          }
          await draft.recover(recovery.values);
          if (current()) onRestore(recovery.values);
        })}>{changed && !compared ? 'Aktuellen Stand vergleichen' : 'Entwurf übernehmen'}</button>}
        <button type="button" className="btn btn-ghost" disabled={busy || locked} onClick={() => run(() => draft.clear())}>Entwurf verwerfen</button>
      </div>
    </>}
  </section>;
}
