import { useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { useEntities, useDataStore } from '../../contexts/DataStoreContext';
import FormModal from '../../components/FormModal';
import FileViewer from '../../components/FileViewer';
import { workspace } from '../../utils/workspaceClient';
import { resolveFileUrl } from '../partyWorkspace/files';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import NamedViews from '../../components/NamedViews';
import useCursorFeed from './useCursorFeed';
import FeedState from './FeedState';
import UndoNotice from './UndoNotice';
import './workCenter.css';

const STATES = { pending: 'Offen', processing: 'In Bearbeitung', review: 'Zur Prüfung', done: 'Geprüft', failed: 'Fehlgeschlagen' };
const processable = row => row.can_process !== false && (['pending', 'failed'].includes(row.status) || (row.status === 'processing' && row.lease_expired));
export default function DocumentIntakeQueue() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') || '';
  const feed = useCursorFeed(`/work-center/documents?limit=25${status ? `&status=${encodeURIComponent(status)}` : ''}`);
  const canWrite = useCanWrite('/documents');
  const store = useDataStore();
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [viewer, setViewer] = useState(null);
  const [pendingNext, setPendingNext] = useState(null);
  const [nextMessage, setNextMessage] = useState(null);
  const [change, setChange] = useState(null);
  const lock = useRef(false);
  const commands = useRef(new Map());
  const reviewRequest = useRef(0);
  const sequence = useRef(null);
  const process = async targets => {
    if (lock.current || targets.length === 0) return;
    lock.current = true; setBusy(true); setError(null); setReport(null);
    const failed = []; const succeeded = [];
    try {
      for (const row of targets) {
        try {
          const signature = `${row.document_id}:${row.document_revision}`;
          if (!commands.current.has(signature)) commands.current.set(signature, workspace.command());
          const result = await api.post(`/work-center/documents/${encodeURIComponent(row.document_id)}/process`, {
            base_revision: row.document_revision, idempotency_key: commands.current.get(signature), use_ai: false,
          });
          if (result?.intake?.status === 'failed') {
            commands.current.delete(signature);
            throw new Error(result.intake.error || 'Die Datei konnte nicht analysiert werden.');
          }
          if (result?.status === 'processing' || result?.intake?.status === 'processing') throw new Error('Die Analyse läuft noch. Bitte die Warteschlange erneut laden.');
          if (!['review', 'done'].includes(result?.intake?.status)) throw new Error('Die Verarbeitung konnte nicht bestätigt werden. Bitte die Warteschlange neu laden.');
          commands.current.delete(signature); succeeded.push(row.document_id);
        } catch (failure) { failed.push({ id: row.document_id, title: row.title, message: failure.message }); }
      }
      setSelected(current => new Set([...current].filter(id => !succeeded.includes(id))));
      setReport({ succeeded: succeeded.length, failed }); feed.retry();
    } finally { lock.current = false; setBusy(false); }
  };
  const openReview = async row => {
    if (lock.current) return;
    const request = ++reviewRequest.current;
    setError(null);
    try {
      const result = await api.get(`/work-center/documents/${encodeURIComponent(row.document_id)}`);
      if (reviewRequest.current === request) {
        const index = feed.items.findIndex(item => item.document_id === row.document_id);
        sequence.current = { current: row.document_id, remaining: feed.items.slice(index + 1), cursor: feed.next_cursor,
          path: `/work-center/documents?limit=25${status ? `&status=${encodeURIComponent(status)}` : ''}`, seen: [row.document_id] };
        setPendingNext(null); setNextMessage(null); setDetail(result);
      }
    } catch (failure) { if (reviewRequest.current === request) setError(failure.message); }
  };
  const loadNext = async pending => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null); setNextMessage('Nächster Beleg wird vorbereitet…');
    try {
      const next = { ...pending, remaining: [...pending.remaining] };
      let row = next.row;
      const visited = new Set();
      while (!row) {
        row = next.remaining.shift();
        if (row && next.seen.includes(row.document_id)) { row = null; continue; }
        if (row || !next.cursor) break;
        if (visited.has(next.cursor)) throw new Error('Die nächste Seite konnte nicht eindeutig bestimmt werden. Bitte die Auswahl neu öffnen.');
        visited.add(next.cursor);
        const page = await api.get(`${next.path}&cursor=${encodeURIComponent(next.cursor)}`);
        next.remaining = page.items || []; next.cursor = page.next_cursor || null;
      }
      if (!row) { setPendingNext(null); setNextMessage('Dokument gespeichert. Kein weiterer Beleg in dieser Auswahl.'); return; }
      next.row = row; setPendingNext(next);
      let fresh = await api.get(`/work-center/documents/${encodeURIComponent(row.document_id)}`);
      if (processable(fresh.intake) && fresh.intake.can_process) {
        const signature = `${row.document_id}:${fresh.intake.document_revision}`;
        if (!commands.current.has(signature)) commands.current.set(signature, workspace.command());
        const result = await api.post(`/work-center/documents/${encodeURIComponent(row.document_id)}/process`, {
          base_revision: fresh.intake.document_revision, idempotency_key: commands.current.get(signature), use_ai: false,
        });
        if (result?.intake?.status === 'failed') { commands.current.delete(signature); throw new Error(result.intake.error || 'Der nächste Beleg konnte nicht analysiert werden.'); }
        if (result?.intake?.status !== 'review') throw new Error('Die nächste Analyse ist noch nicht bestätigt. Bitte erneut laden.');
        commands.current.delete(signature);
        fresh = await api.get(`/work-center/documents/${encodeURIComponent(row.document_id)}`);
      }
      sequence.current = { current: row.document_id, remaining: next.remaining, cursor: next.cursor,
        path: next.path, seen: [...next.seen, row.document_id] };
      setDetail({ ...fresh, carry: pending.carry }); setPendingNext(null); setNextMessage(null);
    } catch (failure) { setError(`Der vorherige Beleg ist gespeichert. ${failure.message}`); setNextMessage(null); }
    finally { lock.current = false; setBusy(false); feed.retry(); }
  };
  const advance = async (documentId, carry) => {
    const current = sequence.current;
    const pending = current?.current === documentId ? { ...current, carry }
      : { remaining: [], cursor: null, path: '', seen: [documentId], carry };
    setDetail(null); setPendingNext(pending);
    store?.invalidateRelated('documents');
    await loadNext(pending);
  };
  const targets = feed.items.filter(row => selected.has(row.document_id) && processable(row));
  return <div className="page work-center"><header className="work-center-header"><div><h1>Dokumenteneingang</h1>
    <p>Erkennungsvorschläge prüfen und zuordnen. Eine Analyse ändert keine Rechnung und keine Zuordnung.</p></div>
    <Link to="/documents?create=1" className="btn btn-primary">Dokumente hochladen</Link></header>
    <div className="work-center-filters"><label>Status<select value={status} disabled={busy} onChange={event => {
      setSelected(new Set()); setReport(null); setParams(event.target.value ? { status: event.target.value } : {});
    }}><option value="">Offener Eingang</option>{Object.entries(STATES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {canWrite && <button type="button" className="btn btn-secondary" disabled={busy || targets.length === 0} onClick={() => process(targets)}>{busy ? 'Wird analysiert…' : `Auswahl analysieren (${targets.length})`}</button>}
    </div>
    <div inert={busy ? true : undefined}><NamedViews context="documents#intake" config={{ column_filters: { status } }} onApply={config => {
      const next = config.column_filters?.status;
      setSelected(new Set()); setReport(null); setParams(next && Object.hasOwn(STATES, next) ? { status: next } : {});
    }} /></div>
    {error && <p role="alert" className="work-inline-error">{error}</p>}
    {nextMessage && <p role="status">{nextMessage}</p>}
    {pendingNext && !busy && <button type="button" className="btn btn-secondary" onClick={() => loadNext(pendingNext)}>Nächsten Beleg erneut laden</button>}
    {change && <UndoNotice key={change.undo_id} change={change} onDismiss={() => setChange(null)}
      onUndone={() => { setChange(null); store?.invalidateRelated('documents'); feed.retry(); }} />}
    {report && <div role={report.failed.length ? 'alert' : 'status'}>{report.succeeded} analysiert{report.failed.length ? ` · ${report.failed.length} fehlgeschlagen` : ''}
      {report.failed.length > 0 && <ul>{report.failed.map(item => <li key={item.id}>{item.title}: {item.message}</li>)}</ul>}</div>}
    <div className="table-scroll"><table className="work-queue-table"><thead><tr>{canWrite && <th>Auswahl</th>}<th>Dokument</th><th>Status</th><th>Aktionen</th></tr></thead>
      <tbody>{feed.items.map(row => <tr key={row.document_id}>
        {canWrite && <td><input type="checkbox" aria-label={`Auswählen: ${row.title}`} disabled={busy || !processable(row)} checked={selected.has(row.document_id)}
          onChange={event => setSelected(current => { const next = new Set(current); if (event.target.checked) next.add(row.document_id); else next.delete(row.document_id); return next; })} /></td>}
        <td><strong>{row.title}</strong>{row.error && <p className="work-inline-error">{row.error}</p>}</td><td>{STATES[row.status] || row.status}</td>
        <td><div className="work-item-actions">
          {canWrite && processable(row) && <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => process([row])}>{row.lease_expired ? 'Analyse fortsetzen' : 'Analysieren'}</button>}
          <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => openReview(row)}>Vorschläge prüfen</button>
          <Link className="btn btn-sm btn-ghost" to={`/duplicate-check?kind=file&id=${encodeURIComponent(row.document_id)}`}>Dubletten prüfen</Link>
        </div></td>
      </tr>)}</tbody></table></div>
    <FeedState feed={feed} empty="Kein Dokumenteneingang für diese Auswahl." />
    {detail && <DocumentReview key={`${detail.document.id}:${detail.intake.revision}`} detail={detail} canWrite={canWrite}
      onPreview={() => setViewer(detail.document)} onClose={() => { reviewRequest.current += 1; setDetail(null); }} onSaved={() => { store?.invalidateRelated('documents'); feed.retry(); }}
      onReviewSaved={result => { if (result.undo_id) setChange({ ...result, record: result.document }); }} onAdvance={advance} />}
    {viewer && <FileViewer fileUrl={viewer.file_url} title={viewer.title} onClose={() => setViewer(null)} />}
  </div>;
}

function DocumentReview({ detail, canWrite, onPreview, onClose, onSaved, onReviewSaved, onAdvance }) {
  const { document, intake } = detail;
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants_all', '/tenants?include_archived=true');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const command = useRef(workspace.command());
  const payload = useRef(null);
  const [carryAssignments, setCarryAssignments] = useState(Boolean(detail.carry));
  const dialogRef = useRef(null);
  const readonly = !canWrite || intake.can_review === false || ['pending', 'processing'].includes(intake.status);
  useModalDialog(dialogRef, onClose, readonly);
  if (readonly) return <div className="modal-overlay" role="presentation"><section ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-label="Dokumentvorschläge" tabIndex={-1}>
    <div className="modal-body"><h2>{document.title}</h2><p className="work-preserve-lines">{intake.result?.summary || (intake.status === 'pending' ? 'Bitte das Dokument zuerst analysieren.' : intake.status === 'processing' ? 'Die Analyse läuft noch.' : 'Keine Erkennungsvorschläge vorhanden.')}</p>
      {resolveFileUrl(document.file_url) && <button type="button" className="btn btn-secondary" onClick={onPreview}>Dokument ansehen</button>}
      <button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button></div></section></div>;
  const initial = { ...document, document_type: intake.result?.document_type || document.document_type,
    description: intake.result?.summary || document.description,
    ...(![document.property_id, document.unit_id, document.tenant_id, document.contract_id].some(Boolean) ? detail.carry || {} : {}) };
  const fields = [
    { key: 'title', label: 'Titel', required: true, hint: <>
      {resolveFileUrl(document.file_url) ? <button type="button" className="btn btn-sm btn-ghost" onClick={onPreview}>Original ansehen</button> : 'Keine Datei vorhanden.'}
      <label className="work-carry-option"><input type="checkbox" checked={carryAssignments} onChange={event => setCarryAssignments(event.target.checked)} /> <span>Zuordnung für den nächsten unzugeordneten Beleg übernehmen</span></label>
    </> },
    { key: 'document_type', label: 'Dokumententyp', hint: 'Vorschläge werden erst mit Speichern verbindlich.' },
    { key: 'description', label: 'Inhalt / Erkennungsvorschlag', type: 'textarea' },
    { key: 'property_id', label: 'Immobilie', type: 'select', clearOnChange: ['unit_id', 'contract_id'], options: properties.map(row => ({ value: row.id, label: row.name })) },
    { key: 'unit_id', label: 'Einheit', type: 'select', clearOnChange: ['contract_id'], options: values => units.filter(row => !values.property_id || row.property_id === values.property_id).map(row => ({ value: row.id, label: row.label })) },
    { key: 'tenant_id', label: 'Partei', type: 'select', options: tenants.map(row => ({ value: row.id, label: row.full_name })) },
    { key: 'contract_id', label: 'Vertrag', type: 'select', options: values => contracts.filter(row => (!values.property_id || row.property_id === values.property_id) && (!values.unit_id || row.unit_id === values.unit_id) && (!values.tenant_id || row.tenant_id === values.tenant_id)).map(row => ({ value: row.id, label: row.contract_number })) },
    { key: 'tags', label: 'Schlagwörter' },
  ];
  const save = async (values, next = false) => {
    const changes = Object.fromEntries(fields.map(field => [field.key, values[field.key]]));
    const signature = JSON.stringify(changes);
    if (payload.current !== null && payload.current !== signature) command.current = workspace.command();
    payload.current = signature;
    const result = await api.post(`/work-center/documents/${encodeURIComponent(document.id)}/review`, { base_revision: intake.revision,
      document_revision: intake.document_revision, changes, idempotency_key: command.current });
    onReviewSaved?.(result);
    if (next) await onAdvance(document.id, carryAssignments ? Object.fromEntries(['property_id', 'unit_id', 'tenant_id', 'contract_id'].map(key => [key, changes[key] || null])) : null);
    else onSaved?.();
  };
  return <FormModal title={`Dokument prüfen · ${document.title}`} fields={fields} initial={initial} onSave={save} onClose={onClose}
    onSaveNext={values => save(values, true)} saveNextLabel="Speichern & nächster Beleg"
    draftContext="documents" draftAnchor={{ kind: 'document', id: document.id }} />;
}
