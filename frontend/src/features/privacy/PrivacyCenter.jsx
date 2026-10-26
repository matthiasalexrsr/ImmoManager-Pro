import { useState } from 'react';
import { api } from '../../api';
import useLookupChoices from '../../hooks/useLookupChoices';
import { usePortalAdminAction, usePortalAdminPage } from '../externalPortal/adminHooks';
import { saveBlob } from '../documentShare/documentShare';
import '../dataTransfer/dataTransfer.css';

const BASE = '/privacy';
const TYPES = {
  document: ['Dokument', '/documents'], e_invoice_intake: ['E-Rechnungseingang', '/e-invoice-intakes'],
  import_batch: ['Importquellen', '/data/import-batches'], portability_export: ['Erstelltes Exportpaket', '/data/portability-exports'],
  portal_case: ['Externe Vorgangskommunikation', '/portal-admin/cases'], portal_identity: ['Externes Zugangskonto', '/portal-admin/grants'],
};
const STATES = { open: 'Offen', fulfilled: 'Erfüllt', partially_fulfilled: 'Teilweise erfüllt', deferred: 'Zurückgestellt', declined: 'Abgelehnt' };
const ACTIONS = { hold: 'Aufbewahrung sperren', release_hold: 'Aufbewahrungssperre aufheben', restrict: 'Veröffentlichung, Suche und KI sperren', release_restriction: 'Verarbeitungssperre aufheben', erase: 'Löschung ausführen' };

async function download(path, filename) {
  const current = api.captureSession(); const blob = await api.getBlob(path); current(); saveBlob(blob, filename);
}

export default function PrivacyCenter() {
  const [area, setArea] = useState('resources'), [target, setTarget] = useState(null);
  return <section className="panel data-transfer"><div className="panel-body">
    <h2>Datenschutz und Aufbewahrung</h2>
    <p>Sperren und Entscheidungen gelten für den gesamten Bestand. Fristablauf löst keine automatische Löschung aus. Originalbelege, Geschäftsdaten und externe Kommunikation werden getrennt geprüft.</p>
    <nav className="transfer-actions" aria-label="Datenschutzbereiche">{[['resources', 'Sperren und Löschungen'], ['requests', 'Auskunfts- und Löschanfragen'], ['restore', 'Journal und Wiederherstellung']].map(([key, label]) =>
      <button className="btn btn-secondary" key={key} aria-pressed={area === key} onClick={() => setArea(key)}>{label}</button>)}</nav>
    {area === 'resources' && <ResourceControls key={target?.id || 'selection'} initialTarget={target} />}{area === 'requests' && <Requests />}{area === 'restore' && <RestoreReview onSelect={item => { setTarget(item); setArea('resources'); }} />}
  </div></section>;
}

function ResourceControls({ initialTarget }) {
  const [kind, setKind] = useState(initialTarget?.kind || 'document'), [skip, setSkip] = useState(0), [id, setId] = useState(initialTarget?.id || ''), [refresh, setRefresh] = useState(0);
  const [page, listError] = usePortalAdminPage(`${TYPES[kind][1]}?skip=${skip}&limit=25`, refresh);
  const [resource, resourceError] = usePortalAdminPage(id ? `${BASE}/resources/${kind}/${encodeURIComponent(id)}` : null, refresh);
  const [reason, setReason] = useState(''), [confirmed, setConfirmed] = useState(false), [notice, setNotice] = useState('');
  const action = usePortalAdminAction();
  const raw = Array.isArray(page) ? page : page?.items || [];
  const options = [...new Map(raw.map(row => [kind === 'portal_identity' ? row.identity_id : row.id, row])).entries()];
  const reload = () => { setRefresh(value => value + 1); setConfirmed(false); };
  return <div><h3>Datensatz und aktuellen Prüfstand wählen</h3>
    <div className="transfer-grid"><label>Datenart<select value={kind} onChange={event => { setKind(event.target.value); setId(''); setSkip(0); setConfirmed(false); setNotice(''); }}>
      {Object.entries(TYPES).map(([key, [label]]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Datensatz<select value={id} onChange={event => { setId(event.target.value); setConfirmed(false); setNotice(''); }}><option value="">Bitte wählen …</option>
        {options.map(([key, row]) => <option key={key} value={key}>{row.title || row.filename || row.email || row.source_system || `${TYPES[kind][0]} vom ${new Date(row.created_at).toLocaleString('de-DE')}`}</option>)}</select></label></div>
    <nav aria-label="Datensatzauswahl"><button className="btn btn-secondary" disabled={!skip || action.busy} onClick={() => { setSkip(skip - 25); setId(''); }}>Vorherige Datensätze</button>
      <button className="btn btn-secondary" disabled={action.busy || (page?.total !== undefined ? skip + 25 >= page.total : raw.length < 25)} onClick={() => { setSkip(skip + 25); setId(''); }}>Weitere Datensätze</button>
      <button className="btn btn-secondary" disabled={action.busy} onClick={reload}>Stand neu laden</button></nav>
    {(listError || resourceError || action.error) && <p role="alert">{listError || resourceError || action.error}</p>}{notice && <p role="status">{notice}</p>}
    {resource && <><h3>{resource.title}</h3><p>Aufbewahrungssperre: {resource.held ? 'Gesetzt' : 'Keine'} · Verarbeitungssperre: {resource.restricted ? 'Gesetzt' : 'Keine'} · Prüfstand {resource.revision}</p>
      <p>{resource.erased_at ? `Löschung dokumentiert am ${new Date(resource.erased_at).toLocaleString('de-DE')}` : resource.retention_until ? `Aufbewahrung mindestens bis ${resource.retention_until}` : 'Keine feste Frist ermittelt; die fachlichen Sperrgründe gelten weiterhin.'}</p>
      {!!resource.blockers.length && <ul>{resource.blockers.map((item, index) => <li key={index}>{item}</li>)}</ul>}
      {resource.erasure_due && <p role="alert">Nach Wiederherstellung erneut auszuführende Löschung. Externe Zugriffe bleiben bis zum Abgleich gesperrt.</p>}
      {kind === 'document' && <p><a href={`/documents?focus_id=${encodeURIComponent(id)}`}>Dokumentakte öffnen</a></p>}
      {!resource.erased_at && <><label>Begründung der Entscheidung<textarea value={reason} minLength={10} maxLength={2000} onChange={event => setReason(event.target.value)} /></label>
        {resource.can_erase && <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> Ich habe die verbleibenden Akten geprüft und bestätige die Löschung dieses Datenbestands.</label>}
        <div className="transfer-actions">{[resource.held ? 'release_hold' : 'hold', resource.restricted ? 'release_restriction' : 'restrict', ...(resource.can_erase ? ['erase'] : [])].map(operation =>
          <button className="btn btn-secondary" key={operation} disabled={action.busy || reason.trim().length < 10 || (operation === 'erase' && !confirmed) || (operation === 'release_restriction' && resource.erasure_due)} onClick={async () => {
            const result = await action.perform(`${BASE}/resources/${kind}/${encodeURIComponent(id)}`, { action: operation, reason, expected_revision: resource.revision, source_sha256: resource.source_sha256 });
            if (result) { setNotice(result.outcome?.retained ? `Entscheidung gespeichert. Weiterhin erhalten: ${result.outcome.retained}.` : 'Entscheidung gespeichert.'); reload(); }
          }}>{ACTIONS[operation]}</button>)}</div></>}
      <details><summary>Entscheidungsverlauf</summary><ul>{resource.decisions?.map((item, index) => <li key={index}>{ACTIONS[item.action] || item.action} · {new Date(item.created_at).toLocaleString('de-DE')}<p>{item.reason}</p>
        {(item.result?.retained || item.result?.outcome?.retained) && <p>Weiterhin erhalten: {item.result.retained || item.result.outcome.retained}</p>}</li>)}</ul></details>
    </>}
  </div>;
}

function Requests() {
  const [kind, setKind] = useState('tenant'), [party, setParty] = useState(''), [type, setType] = useState('access'), [verification, setVerification] = useState(''), [due, setDue] = useState('');
  const [refresh, setRefresh] = useState(0), [skip, setSkip] = useState(0), [selected, setSelected] = useState(''), [error, setError] = useState('');
  const choices = useLookupChoices({ parties: kind === 'tenant' ? '/tenants' : '/contacts' });
  const [page, listError] = usePortalAdminPage(`${BASE}/requests?skip=${skip}&limit=25`, refresh);
  const [detail, detailError] = usePortalAdminPage(selected ? `${BASE}/requests/${selected}` : null, refresh);
  const [outcome, setOutcome] = useState('partially_fulfilled'), [reason, setReason] = useState('');
  const action = usePortalAdminAction(), reload = () => setRefresh(value => value + 1);
  return <div><h3>Geprüfte Anfrage erfassen</h3><form className="transfer-grid" onSubmit={async event => {
    event.preventDefault(); const result = await action.perform(`${BASE}/requests`, { subject_kind: kind, subject_id: party, request_type: type, verification, due_on: due });
    if (result) { setSelected(result.id); reload(); }
  }}><label>Parteiart<select value={kind} onChange={event => { setKind(event.target.value); setParty(''); }}><option value="tenant">Mieter</option><option value="contact">Kontakt / Eigentümer</option></select></label>
    <label>Geprüfte Partei<select required value={party} onChange={event => setParty(event.target.value)}><option value="">Bitte wählen …</option>{(choices.data.parties || []).map(row =>
      <option key={row.id} value={row.id}>{row.full_name || [row.first_name, row.last_name].filter(Boolean).join(' ') || row.company_name}</option>)}</select></label>
    <label>Anfrage<select value={type} onChange={event => setType(event.target.value)}><option value="access">Datenauskunft</option><option value="erasure">Löschanfrage</option></select></label>
    <label>Bearbeitungsfrist<input type="date" required value={due} onChange={event => setDue(event.target.value)} /></label>
    <label>Identitätsprüfung<textarea required minLength={10} maxLength={2000} value={verification} onChange={event => setVerification(event.target.value)} /></label>
    <button className="btn btn-primary" disabled={action.busy || !choices.ready}>Anfrage erfassen</button></form>
    {(error || listError || detailError || choices.error || action.error) && <p role="alert">{error || listError || detailError || choices.error || action.error}</p>}
    <h3>Bearbeitung und Nachweise</h3><button className="btn btn-secondary" onClick={reload}>Aktuellen Stand laden</button>
    <ul className="transfer-list">{page?.items.map(row => <li key={row.id}>{row.request_type === 'access' ? 'Auskunft' : 'Löschung'} · {STATES[row.state]} · Frist {row.due_on}
      <button className="btn btn-secondary" onClick={() => setSelected(row.id)}>Bestand und Entscheidung prüfen</button></li>)}</ul>
    <nav aria-label="Datenschutzanfragen"><button className="btn btn-secondary" disabled={!skip} onClick={() => setSkip(skip - 25)}>Zurück</button>
      <span> {page?.total || 0} Anfragen </span><button className="btn btn-secondary" disabled={!page || skip + 25 >= page.total} onClick={() => setSkip(skip + 25)}>Weiter</button></nav>
    {detail && <><h3>{detail.data.subject.full_name || detail.data.subject.last_name} · {STATES[detail.state]}</h3>
      <p>Vor Weitergabe: Inhalt prüfen und fremde personenbezogene Daten schwärzen. Ganze Sammelimporte werden nicht automatisch in die Auskunft aufgenommen.</p>
      <button className="btn btn-secondary" onClick={() => download(`${BASE}/requests/${selected}/export`, 'Datenauskunft-zur-Pruefung.json').catch(failure => setError(failure.message))}>Auskunft zur Inhaltsprüfung herunterladen</button>
      <details><summary>Vorhandene Bestände und Sperren</summary><ul>{Object.entries(detail.retained_records).map(([name, count]) => <li key={name}>{name}: {count}</li>)}</ul>
        <p>{detail.data.extensions.portal_messages.length} externe Nachrichten · {detail.data.extensions.portal_images.length} Bilder · {detail.data.extensions.e_invoice_intakes.length} Rechnungseingänge</p></details>
      <form className="transfer-grid" onSubmit={async event => { event.preventDefault(); const result = await action.perform(`${BASE}/requests/${selected}/decision`, { expected_revision: detail.revision, source_sha256: detail.source_sha256, outcome, reason }); if (result) reload(); }}>
        <label>Entscheidung<select value={outcome} onChange={event => setOutcome(event.target.value)}>{Object.entries(STATES).filter(([key]) => key !== 'open').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Begründung einschließlich zurückbehaltener Daten<textarea required minLength={10} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <button className="btn btn-primary" disabled={action.busy}>Entscheidung für diesen Prüfstand speichern</button></form>
    </>}
  </div>;
}

function RestoreReview({ onSelect }) {
  const [refresh, setRefresh] = useState(0), [file, setFile] = useState(null), [error, setError] = useState(''), [reason, setReason] = useState(''), [confirmed, setConfirmed] = useState(false);
  const [review, reviewError] = usePortalAdminPage(`${BASE}/restore-review`, refresh);
  const action = usePortalAdminAction(), reload = () => { setRefresh(value => value + 1); setConfirmed(false); };
  return <div><h3>Aktuelle Entscheidungen getrennt von Sicherungen aufbewahren</h3>
    <p>Das Journal enthält Sperren und Löschvermerke mit Begründungen. Bewahren Sie eine aktuelle Kopie geschützt außerhalb alter Sicherungen auf. Nach Wiederherstellung zuerst dieses Journal abgleichen; ein Import kann bestehende Sperren nur verstärken.</p>
    <button className="btn btn-secondary" onClick={() => download(`${BASE}/journal`, 'Datenschutzjournal.json').catch(failure => setError(failure.message))}>Aktuelles Datenschutzjournal herunterladen</button>
    <label>Journaldatei zum Abgleich<input type="file" accept="application/json,.json" onChange={async event => {
      setFile(null); setError(''); const selected = event.target.files?.[0]; if (!selected) return;
      try { if (selected.size > 16 * 1024 * 1024) throw new Error('Journal ist größer als 16 MiB.'); const value = JSON.parse(await selected.text());
        if (value.format !== 'immomanager-privacy-controls/1' || !Array.isArray(value.controls) || !value.sha256) throw new Error('Keine gültige Journaldatei.'); setFile(value);
      } catch (failure) { setError(failure.message); }
    }} /></label>
    {file && <p>{file.controls.length} Entscheidungen zum Abgleich vorbereitet.</p>}
    <label>Begründung und Grundlage des Abgleichs<textarea minLength={20} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <button className="btn btn-secondary" disabled={action.busy || !file || reason.trim().length < 20} onClick={async () => {
      const result = await action.perform(`${BASE}/journal/import`, { controls: file.controls, source_sha256: file.sha256, reason }); if (result) { setFile(null); reload(); }
    }}>Vorbereitetes Journal abgleichen</button>
    {(error || reviewError || action.error) && <p role="alert">{error || reviewError || action.error}</p>}
    {review && <><h3>{review.pending ? 'Wiederherstellung noch gesperrt' : 'Keine Wiederherstellungsprüfung ausstehend'}</h3>
      <p>{review.reason}</p>{review.pending && <><p>Suche, KI und externes Portal bleiben bis zur Prüfung geschlossen. Einzelne Portalzugänge und Dokumentfassungen benötigen danach zusätzlich ihre eigenen Freigaben.</p>
        {!!review.pending_erasure.length && <p role="alert">{review.pending_erasure.length} vorgemerkte Löschungen sind noch offen. Diese Daten zuerst im Bereich Sperren und Löschungen prüfen.</p>}
        <ul>{review.pending_erasure.map(item => <li key={`${item.kind}:${item.id}`}><button className="btn btn-secondary" onClick={() => onSelect(item)}>{item.title || TYPES[item.kind]?.[0] || 'Datensatz'} prüfen</button></li>)}</ul>
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> Ich habe aktuelle Lösch- und Sperrentscheidungen aus allen verfügbaren Nachweisen abgeglichen.</label>
        <button className="btn btn-primary" disabled={action.busy || !confirmed || reason.trim().length < 20 || !!review.pending_erasure.length} onClick={async () => {
          const result = await action.perform(`${BASE}/restore-review`, { expected_revision: review.revision, journal_sha256: review.journal_sha256, reason, decisions_reconciled: true }); if (result) reload();
        }}>Geprüften Abgleich bestätigen</button></>}
      <button className="btn btn-secondary" onClick={reload}>Prüfstand neu laden</button>
    </>}
  </div>;
}
