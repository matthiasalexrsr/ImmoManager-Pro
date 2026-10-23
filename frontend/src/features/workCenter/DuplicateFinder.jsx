import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import FormModal from '../../components/FormModal';
import { workspace } from '../../utils/workspaceClient';
import './workCenter.css';

const TYPES = { contact: { label: 'Kontakte', endpoint: '/contacts' }, invoice: { label: 'Rechnungen', endpoint: '/invoices' }, file: { label: 'Dateien', endpoint: '/documents' } };
const REASONS = { email: 'Gleiche E-Mail-Adresse', phone: 'Gleiche Telefonnummer', name_address: 'Name und Anschrift stimmen überein',
  same_content: 'Identischer Dateiinhalt', archived_content: 'Identischer Inhalt einer archivierten Fassung', same_number: 'Gleiche Rechnungsnummer', same_amount_near_date: 'Gleicher Betrag bei ähnlichem Rechnungsdatum' };
const CONFIDENCE = { high: 'Hohe Übereinstimmung', medium: 'Mögliche Übereinstimmung', confirmed: 'Bestätigte Übereinstimmung' };
const rowTitle = row => row.title || row.display_name || row.company_name || [row.first_name, row.last_name].filter(Boolean).join(' ') || row.invoice_number || row.id;
export default function DuplicateFinder() {
  const [params, setParams] = useSearchParams();
  const kind = Object.hasOwn(TYPES, params.get('kind')) ? params.get('kind') : 'file';
  const id = params.get('id') || '';
  const [records, setRecords] = useState([]);
  const [error, setError] = useState(null);
  const [lookup, setLookup] = useState({ kind, skip: 0 });
  const [lookupBusy, setLookupBusy] = useState(false);
  const [moreRecords, setMoreRecords] = useState(false);
  const [lookupAttempt, setLookupAttempt] = useState(0);
  const skip = lookup.kind === kind ? lookup.skip : 0;
  useEffect(() => {
    const request = new AbortController();
    if (!skip) setRecords([]);
    setError(null); setLookupBusy(true);
    api.get(`${TYPES[kind].endpoint}?skip=${skip}&limit=50`, { signal: request.signal }).then(items => {
      if (!Array.isArray(items)) throw new Error('Die Datensätze konnten nicht gelesen werden.');
      if (!request.signal.aborted) {
        setRecords(current => skip ? [...current, ...items.filter(item => !current.some(old => old.id === item.id))] : items);
        setMoreRecords(items.length === 50);
      }
    }).catch(failure => { if (!request.signal.aborted) setError(failure.message); })
      .finally(() => { if (!request.signal.aborted) setLookupBusy(false); });
    return () => request.abort();
  }, [kind, skip, lookupAttempt]);
  return <div className="page work-center"><header><h1>Dubletten prüfen</h1><p>Mögliche doppelte Kontakte, Rechnungen und identische Dateien prüfen. Bewusst getrennte Datensätze können Sie mit Begründung kennzeichnen.</p></header>
    {kind === 'file' && <p className="text-muted">Verglichen werden archivierte Fassungen und analysierte Dateien. Die angezeigte Abdeckung zeigt, welche übrigen Dateien noch geprüft werden müssen.</p>}
    <div className="work-center-filters"><label>Bereich<select value={kind} onChange={event => setParams({ kind: event.target.value })}>
      {Object.entries(TYPES).map(([value, type]) => <option key={value} value={value}>{type.label}</option>)}</select></label>
      <label>Datensatz<select value={id} onChange={event => setParams({ kind, id: event.target.value })}><option value="">Bitte wählen</option>
        {id && !records.some(row => row.id === id) && <option value={id}>Ausgewählter Datensatz</option>}
        {records.map(row => <option key={row.id} value={row.id}>{rowTitle(row)}</option>)}</select></label>
      {moreRecords && <button type="button" className="btn btn-secondary" disabled={lookupBusy || Boolean(error)} onClick={() => setLookup({ kind, skip: skip + 50 })}>Weitere Datensätze laden</button>}
      {lookupBusy && <span role="status">Datensätze werden geladen…</span>}
    </div>
    {error && <p role="alert">Die Datensätze konnten nicht geladen werden. {error} <button type="button" className="btn btn-sm btn-secondary" disabled={lookupBusy} onClick={() => setLookupAttempt(value => value + 1)}>Datensätze erneut laden</button></p>}
    {id && <Check key={`${kind}:${id}`} kind={kind} id={id} />}
  </div>;
}

function Check({ kind, id }) {
  const canWrite = useCanWrite(TYPES[kind].endpoint);
  const [source, setSource] = useState(null);
  const [page, setPage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [exception, setException] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const requestRef = useRef(null);
  const lock = useRef(false);
  useEffect(() => {
    const request = new AbortController(); requestRef.current = request;
    setBusy(true); setError(null);
    api.get(`${TYPES[kind].endpoint}/${encodeURIComponent(id)}`, { signal: request.signal }).then(async record => {
      const result = await api.post('/work-center/duplicates/check', { kind,
        candidate: kind === 'file' ? { document_id: id } : record, exclude_id: id, limit: 25 }, { signal: request.signal });
      if (!request.signal.aborted) { setSource(record); setPage(result); }
    }).catch(failure => { if (!request.signal.aborted) setError(failure.message); })
      .finally(() => { if (!request.signal.aborted) setBusy(false); });
    return () => request.abort();
  }, [kind, id, attempt]);
  const loadMore = async () => {
    if (lock.current || !page?.next_cursor || !source) return;
    lock.current = true; setBusy(true); setError(null);
    const request = requestRef.current;
    try {
      const next = await api.post('/work-center/duplicates/check', { kind, candidate: kind === 'file' ? { document_id: id } : source,
        exclude_id: id, limit: 25, cursor: page.next_cursor }, { signal: request.signal });
      if (!request.signal.aborted) setPage(current => ({ ...next, items: [...current.items, ...next.items.filter(item => !current.items.some(previous => previous.entity_id === item.entity_id))] }));
    } catch (failure) { if (!request.signal.aborted) setError(failure.message); }
    finally { lock.current = false; if (!request.signal.aborted) setBusy(false); }
  };
  return <section aria-label="Dublettenprüfung">
    {source && <h2>{rowTitle(source)}</h2>}
    {busy && <p role="status">Dubletten werden geprüft…</p>}
    {error && <p role="alert">{error} <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => setAttempt(value => value + 1)}>Erneut prüfen</button></p>}
    {page && <><p className="text-muted">{page.items.length} mögliche Übereinstimmungen geladen.</p>
      {page.coverage && <p role={page.coverage.complete ? 'status' : 'alert'}>{page.coverage.note}
        {' '}{page.coverage.indexed_count} Inhalte geprüft · {page.coverage.unindexed_count} noch nicht erfasst.
        {!page.coverage.complete && page.coverage.pending_href && <> <Link to={page.coverage.pending_href}>Offene Dateien analysieren</Link></>}
      </p>}
      {page.incomplete && <p role="status">Für eine vollständige Prüfung fehlen noch Angaben zum ausgewählten Datensatz.</p>}
      <ul className="work-item-list">{page.items.map(item => <li key={item.entity_id} className="work-item"><h3><Link to={item.href}>{item.title}</Link></h3>
        <p>{REASONS[item.reason] || item.reason}{item.confidence != null && ` · ${CONFIDENCE[item.confidence] || (typeof item.confidence === 'number' ? `${Math.round(item.confidence * 100)} % Übereinstimmung` : 'Übereinstimmung prüfen')}`}</p>
        {item.exception ? <p>Bewusst getrennt: {item.exception.reason}</p> : canWrite && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setException(item)}>Bewusst getrennt lassen</button>}
      </li>)}</ul>
      {!page.items.length && !busy && <p>{page.incomplete || page.coverage?.complete === false ? 'In den bisher geprüften Inhalten wurde keine Übereinstimmung gefunden.' : 'Keine Übereinstimmungen gefunden.'}</p>}
      {page.next_cursor && <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={busy}>Weitere Übereinstimmungen</button>}
    </>}
    {exception && source && <ExceptionDialog kind={kind} source={source} match={exception} onClose={() => setException(null)}
      onSaved={() => setAttempt(value => value + 1)} />}
  </section>;
}

function ExceptionDialog({ kind, source, match, onClose, onSaved }) {
  const command = useRef(workspace.command());
  const payload = useRef(null);
  const save = async values => {
    if (!values.reason?.trim()) throw new Error('Bitte begründen, warum die Datensätze getrennt bleiben.');
    if (payload.current !== null && payload.current !== values.reason) command.current = workspace.command();
    payload.current = values.reason;
    await api.post('/work-center/duplicates/exceptions', { kind, entity_id: source.id, duplicate_id: match.entity_id,
      base_revision: source.updated_at, duplicate_revision: match.revision, reason: values.reason.trim(), idempotency_key: command.current });
    onSaved?.();
  };
  return <FormModal title={`Getrennte Datensätze bestätigen · ${match.title}`} fields={[{ key: 'reason', label: 'Begründung', type: 'textarea', required: true }]}
    onSave={save} onClose={onClose} autosave={false} />;
}
