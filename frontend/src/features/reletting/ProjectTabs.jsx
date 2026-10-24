import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CalendarPlus, ClipboardCopy, FileText, Paperclip, UserCheck, UserX } from 'lucide-react';
import { api } from '../../api';
import DataTable from '../../components/DataTable';
import FormModal from '../../components/FormModal';
import PdfPreview from '../../components/PdfPreview';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { useAuth } from '../../contexts/AuthContext';
import { formatBytes, formatDate, formatDateTime, formatMoney } from '../../utils/format';
import { holdNewEntry } from '../../utils/newEntry';
import { readAssistantDraft, writeAssistantDraft } from '../assistant/assistantDrafts';
import {
  APPLICANT_BADGE, APPLICANT_FIELDS, APPLICANT_STATUS, CRITERION_STATE, DOCUMENTS, EMPLOYMENT, VIEWING_FIELDS,
  VIEWING_STATUS, applicantPayload, viewingPayload,
} from './relettingModel';

const CLOSED_OUT = ['rejected', 'withdrawn'];
const isActive = row => !CLOSED_OUT.includes(row.status);
const stars = value => (value ? `${value} von 5` : '—');
// a viewing as the datetime-local input shows it
const localInput = value => (value ? String(value).slice(0, 16) : '');

function Badge({ status }) {
  return <span className={`badge ${APPLICANT_BADGE[status] || 'badge-gray'}`}>{APPLICANT_STATUS[status] || status}</span>;
}

// ─── Interessenten ───────────────────────────────────────────────────────────

export function ApplicantsTab({ data, path, canWrite, onChanged }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [form, setForm] = useState(null);            // 'create' | applicant row
  const [viewingFor, setViewingFor] = useState(null);
  const [filesOf, setFilesOf] = useState(null);
  const rows = data.applicants.map(row => ({ ...row, documents: DOCUMENTS.filter(([key]) => row[key]).length }));
  const columns = [
    { key: 'full_name', label: 'Name', filterType: 'text', render: (value, row) => (
      canWrite ? <button type="button" className="link-button" onClick={() => setForm(row)}>{value}</button> : value) },
    { key: 'status', label: 'Status', filterType: 'select', render: value => <Badge status={value} /> },
    { key: 'household_size', label: 'Personen', type: 'number', align: 'right', render: value => value ?? '—' },
    { key: 'net_income', label: 'Nettoeinkommen', type: 'number', align: 'right', render: value => (value == null ? '—' : formatMoney(value)) },
    { key: 'rent_share', label: 'Mietbelastung', type: 'number', align: 'right',
      render: value => (value == null ? '—' : `${String(value).replace('.', ',')}\u00a0%`) },
    { key: 'move_in_date', label: 'Einzug', render: value => formatDate(value) },
    { key: 'documents', label: 'Unterlagen', type: 'number', align: 'right', render: value => `${value} / ${DOCUMENTS.length}` },
    { key: 'met', label: 'Kriterien erfüllt', type: 'number', align: 'right',
      render: (value, row) => `${value} / ${row.criteria.length}` },
    { key: 'viewing_rating', label: 'Eindruck', render: value => stars(value) },
    { key: 'source', label: 'Quelle', hidden: true },
    { key: 'email', label: 'E-Mail', hidden: true },
    { key: 'phone', label: 'Telefon', hidden: true },
  ];
  const decline = async row => {
    if (!await confirm(`${row.full_name} absagen? Es wird keine Nachricht verschickt; bitte selbst informieren.`, { action: 'confirm' })) return;
    try { onChanged(await api.post(`${path}/reject`, { lead_ids: [row.id] })); } catch (failure) { toast.error(failure.message); }
  };
  const save = async values => {
    const row = form === 'create' ? null : form;
    onChanged(row ? await api.put(`${path}/applicants/${encodeURIComponent(row.id)}`, applicantPayload(values, row))
      : await api.post(`${path}/applicants`, applicantPayload(values, null)));
  };
  return <>
    <p className="text-muted reletting-intro">Nur erfassen, was für die Entscheidung nötig ist: vor der Besichtigung Name und
      Kontakt, danach Haushalt und Einkommen, vor dem Vertrag die Bonitätsauskunft. Den Ausweis nur vorzeigen lassen.</p>
    <DataTable title="Bewerbungen" columns={columns} data={rows} writeArea="/reletting" settingsKey="reletting-applicants"
      onAdd={canWrite ? () => setForm('create') : undefined} addLabel="Bewerbung erfassen"
      onEdit={canWrite ? row => setForm(row) : undefined}
      rowActions={row => [
        { label: 'Unterlagen und Fotos', icon: <Paperclip size={15} aria-hidden="true" />, onClick: () => setFilesOf(row) },
        ...(canWrite && isActive(row) ? [
          { label: 'Besichtigung planen', icon: <CalendarPlus size={15} aria-hidden="true" />, write: true, onClick: () => setViewingFor(row) }] : []),
        ...(canWrite && isActive(row) && row.status !== 'accepted' ? [
          { label: 'Absagen', icon: <UserX size={15} aria-hidden="true" />, write: true, onClick: () => decline(row) }] : []),
      ]}
      emptyText="Noch keine Bewerbung erfasst." />
    {form && <FormModal title={form === 'create' ? 'Bewerbung erfassen' : `Bewerbung von ${form.full_name}`}
      fields={form !== 'create' && form.status === 'accepted' ? APPLICANT_FIELDS.filter(f => f.key !== 'status') : APPLICANT_FIELDS}
      initial={form === 'create' ? null : form} autosave={false} onSave={save} onClose={() => setForm(null)} />}
    {viewingFor && <ViewingForm data={data} path={path} initial={{ lead_id: viewingFor.id }} onChanged={onChanged}
      onClose={() => setViewingFor(null)} />}
    {filesOf && <AttachmentsDialog applicant={data.applicants.find(row => row.id === filesOf.id) || filesOf} path={path}
      canWrite={canWrite} onChanged={onChanged} onClose={() => setFilesOf(null)} />}
  </>;
}

function ViewingForm({ data, path, initial, viewing, onChanged, onClose }) {
  const candidates = data.applicants.filter(row => isActive(row) || row.id === initial?.lead_id);
  const fields = VIEWING_FIELDS(candidates).map(field => (viewing && field.key === 'lead_id' ? { ...field, type: 'hidden' } : field));
  return <FormModal title={viewing ? `Besichtigung ${viewing.lead_name || ''}`.trim() : 'Besichtigung planen'} fields={fields}
    initial={viewing ? { ...viewing, scheduled_at: localInput(viewing.scheduled_at), rating: viewing.rating ? String(viewing.rating) : '' }
      : initial} autosave={false}
    onSave={async values => {
      const payload = viewingPayload({ ...values, lead_id: viewing ? viewing.lead_id : values.lead_id });
      onChanged(viewing ? await api.put(`${path}/viewings/${encodeURIComponent(viewing.id)}`, payload)
        : await api.post(`${path}/viewings`, payload));
    }} onClose={onClose} />;
}

// An applicant's documents and photos: kept with the applicant and deleted with them.
function AttachmentsDialog({ applicant, path, canWrite, onChanged, onClose }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const closeRef = useRef(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  useEffect(() => {
    const keydown = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [onClose]);
  const upload = async event => {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) { toast.error('Bitte eine Datei wählen.'); return; }
    const form = new FormData();
    form.append('file', file);
    form.append('title', title || file.name);
    setBusy(true);
    try {
      onChanged(await api.upload(`${path}/applicants/${encodeURIComponent(applicant.id)}/attachments`, form));
      setTitle('');
      if (fileRef.current) fileRef.current.value = '';
    } catch (failure) { toast.error(failure.message); }
    setBusy(false);
  };
  const remove = async attachment => {
    if (!await confirm(`„${attachment.title}“ endgültig löschen?`, { action: 'delete' })) return;
    try { onChanged(await api.del(`${path}/attachments/${encodeURIComponent(attachment.id)}`)); } catch (failure) { toast.error(failure.message); }
  };
  return (
    <div className="modal-overlay" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="modal reletting-files" role="dialog" aria-modal="true" aria-labelledby="reletting-files-title">
        <div className="modal-header">
          <h3 id="reletting-files-title">Unterlagen von {applicant.full_name}</h3>
          <button ref={closeRef} type="button" className="btn-close" onClick={onClose} aria-label="Schließen">×</button>
        </div>
        <div className="modal-body">
          {applicant.attachments.length === 0 ? <p className="text-muted">Noch keine Unterlage.</p> : (
            <ul className="reletting-file-list">
              {applicant.attachments.map(attachment => (
                <li key={attachment.id}>
                  <FileText size={16} aria-hidden="true" />
                  <a href={attachment.file_url} target="_blank" rel="noopener noreferrer">{attachment.title}</a>
                  <span className="text-muted reletting-small">{attachment.kind === 'photo' ? 'Foto' : 'Dokument'}
                    {attachment.size ? ` · ${formatBytes(attachment.size)}` : ''} · {formatDate(attachment.created_at)}</span>
                  {canWrite && <button type="button" className="btn btn-sm btn-ghost" onClick={() => remove(attachment)}
                    aria-label={`${attachment.title} löschen`}>Löschen</button>}
                </li>
              ))}
            </ul>
          )}
          {canWrite && <form className="reletting-upload" onSubmit={upload}>
            <label htmlFor="reletting-file">Datei (PDF, Bild, Office-Dokument)</label>
            <input id="reletting-file" ref={fileRef} type="file" disabled={busy} />
            <label htmlFor="reletting-file-title">Bezeichnung</label>
            <input id="reletting-file-title" value={title} onChange={event => setTitle(event.target.value)} disabled={busy}
              placeholder="z. B. Selbstauskunft, Gehaltsnachweis Juli" />
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{busy ? 'Wird hochgeladen …' : 'Hochladen'}</button>
          </form>}
          <p className="text-muted reletting-small">Die Unterlagen gehören zur Bewerbung und werden mit ihr gelöscht.</p>
        </div>
      </div>
    </div>
  );
}

// ─── Besichtigungen ──────────────────────────────────────────────────────────

export function ViewingsTab({ data, path, canWrite, onChanged }) {
  const [form, setForm] = useState(null);       // 'create' | viewing
  const columns = [
    { key: 'scheduled_at', label: 'Termin', render: value => formatDateTime(value) },
    { key: 'lead_name', label: 'Bewerber', filterType: 'text' },
    { key: 'status', label: 'Status', filterType: 'select', render: value => VIEWING_STATUS[value] || value },
    { key: 'rating', label: 'Eindruck', render: value => stars(value) },
    { key: 'agent', label: 'Durchgeführt von', render: value => value || '—' },
    { key: 'notes', label: 'Notizen', wrap: true, render: value => value || '—' },
  ];
  return <>
    <p className="text-muted reletting-intro">Geplante Termine stehen auch im <Link to="/viewings">Besichtigungskalender</Link>.
      Nach dem Termin Status, Eindruck und Notizen festhalten; sie fließen in den Vergleich ein.</p>
    <DataTable title="Besichtigungen" columns={columns} data={data.viewings} writeArea="/reletting" settingsKey="reletting-viewings"
      onAdd={canWrite && data.applicants.some(isActive) ? () => setForm('create') : undefined} addLabel="Besichtigung planen"
      onEdit={canWrite ? row => setForm(row) : undefined}
      emptyText={data.applicants.some(isActive) ? 'Noch keine Besichtigung geplant.' : 'Zuerst eine Bewerbung erfassen.'} />
    {form && <ViewingForm data={data} path={path} viewing={form === 'create' ? null : form} initial={null}
      onChanged={onChanged} onClose={() => setForm(null)} />}
  </>;
}

// ─── Vergleich ───────────────────────────────────────────────────────────────

export function ComparisonTab({ data, path, canWrite, onChanged, onGo }) {
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const owner = useAuth()?.user?.id;
  const [busy, setBusy] = useState(false);
  const rows = data.applicants.filter(isActive);
  if (!rows.length) return <p className="text-muted">Noch keine offene Bewerbung zum Vergleichen.
    {' '}<button type="button" className="link-button" onClick={() => onGo('applicants')}>Bewerbung erfassen</button></p>;
  const criteria = rows[0].criteria.map(criterion => ({ key: criterion.key, label: criterion.label }));
  const accepted = data.applicants.find(row => row.status === 'accepted');

  const take = async row => {
    if (!await confirm(`${row.full_name} als Mieter übernehmen? Es wird ein Mieterdatensatz angelegt und die Miete der Einheit auf `
      + 'das Angebot gesetzt; den Mietvertrag legen Sie danach selbst an.', { action: 'confirm' })) return;
    setBusy(true);
    try {
      const result = onChanged(await api.post(`${path}/accept`, { lead_id: row.id, apply_rent: true }));
      toast.success(`${row.full_name} ist als Mieter angelegt.${result.rent_applied ? ' Die Miete der Einheit entspricht jetzt dem Angebot.' : ''}`);
      onGo('closing');
    } catch (failure) { toast.error(failure.message); }
    setBusy(false);
  };
  const askAssistant = async () => {
    setBusy(true);
    try {
      const { question } = await api.get(`${path}/ai-question`);
      try {
        writeAssistantDraft(owner, 'new', { ...readAssistantDraft(owner, 'new'), body: question, data_scope: 'none',
          context: [], context_explicit: false });
        navigate('/assistant');
      } catch {
        await navigator.clipboard?.writeText(question);
        toast.success('Die Frage ist in der Zwischenablage. Im KI-Assistenten einfügen und selbst abschicken.');
      }
    } catch (failure) { toast.error(failure.message); }
    setBusy(false);
  };

  return <>
    <p className="text-muted reletting-intro">Alle Bewerbungen nach denselben Kriterien des Angebots. Die Tabelle wertet nicht
      selbst; entscheiden Sie anhand der Fakten. Merkmale nach § 1 AGG (Herkunft, Geschlecht, Religion, Behinderung, Alter,
      sexuelle Identität) dürfen keine Rolle spielen.</p>
    <div className="reletting-compare-actions">
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={askAssistant}>
        KI-Vergleich vorbereiten</button>
      <span className="text-muted reletting-small">Öffnet den KI-Assistenten mit einer pseudonymisierten Frage (ohne Namen,
        Kontaktdaten und Notizen); abgeschickt wird erst, wenn Sie es tun.</span>
    </div>
    <div className="table-scroll">
      <table className="data-table reletting-compare" aria-label="Vergleich der Bewerbungen">
        <thead><tr><th scope="col">Kriterium</th>
          {rows.map(row => <th key={row.id} scope="col">{row.full_name}<div><Badge status={row.status} /></div></th>)}</tr></thead>
        <tbody>
          {criteria.map(criterion => <tr key={criterion.key}><th scope="row">{criterion.label}</th>
            {rows.map(row => {
              const cell = row.criteria.find(item => item.key === criterion.key);
              const state = CRITERION_STATE[cell.state];
              return <td key={row.id} className={state.className}>
                <span aria-hidden="true" className="reletting-mark">{state.symbol}</span>
                <span className="sr-only">{state.label}: </span>{cell.detail}</td>;
            })}</tr>)}
          <tr><th scope="row">Beschäftigung</th>{rows.map(row => <td key={row.id}>{EMPLOYMENT[row.employment] || '—'}</td>)}</tr>
          <tr><th scope="row">Mietbelastung</th>{rows.map(row => <td key={row.id}>
            {row.rent_share == null ? '—' : `${String(row.rent_share).replace('.', ',')}\u00a0%`}</td>)}</tr>
          <tr><th scope="row">Eindruck bei der Besichtigung</th>{rows.map(row => <td key={row.id}>{stars(row.viewing_rating)}</td>)}</tr>
          <tr><th scope="row">Eigene Bewertung</th>{rows.map(row => <td key={row.id}>{stars(row.rating)}</td>)}</tr>
          <tr className="reletting-compare-total"><th scope="row">Kriterien erfüllt</th>
            {rows.map(row => <td key={row.id}><strong>{row.met} von {row.criteria.length}</strong>
              {row.not_met > 0 && <span className="text-muted"> · {row.not_met} nicht erfüllt</span>}</td>)}</tr>
          {canWrite && <tr><th scope="row"><span className="sr-only">Aktion</span></th>
            {rows.map(row => <td key={row.id}>{row.status === 'accepted' ? <span className="badge badge-green">Übernommen</span>
              : !accepted && <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => take(row)}>
                <UserCheck size={14} aria-hidden="true" /> Als Mieter übernehmen</button>}</td>)}</tr>}
        </tbody>
      </table>
    </div>
  </>;
}

// ─── Exposé & Portale ────────────────────────────────────────────────────────

export function ExposeTab({ data, path, canWrite, onChanged, onEdit }) {
  const toast = useToast();
  const [text, setText] = useState(null);
  const [pdf, setPdf] = useState(null);
  const [busy, setBusy] = useState(false);
  const objectUrl = useRef(null);
  const updatedAt = data.project.updated_at;
  useEffect(() => {
    const controller = new AbortController();
    api.get(`${path}/portal-text`, { signal: controller.signal }).then(setText)
      .catch(failure => { if (!controller.signal.aborted) toast.error(failure.message); });
    return () => controller.abort();
  }, [path, updatedAt, toast]);
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, []);

  const showExpose = async () => {
    setBusy(true);
    try {
      const blob = await api.getBlob(`${path}/expose`);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(blob);
      setPdf(objectUrl.current);
    } catch (failure) { toast.error(failure.message); }
    setBusy(false);
  };
  const copy = async (label, value) => {
    try { await navigator.clipboard.writeText(value); toast.success(`${label} kopiert.`); }
    catch { toast.error('Kopieren war nicht möglich. Bitte den Text markieren und selbst kopieren.'); }
  };
  const listing = async () => {
    setBusy(true);
    try {
      const result = onChanged(await api.post(`${path}/listing`, {}));
      toast.success(data.listing ? 'Inserat aktualisiert.' : 'Inserat als Entwurf angelegt.');
      return result;
    } catch (failure) { toast.error(failure.message); }
    finally { setBusy(false); }
    return null;
  };
  const missing = text?.missing || data.missing_for_ad;
  return <>
    {missing.length > 0 && <div role="note" className="alert alert-warning">Für eine Anzeige fehlt noch: {missing.join(', ')}.
      {canWrite && <> <button type="button" className="link-button" onClick={onEdit}>Angebot ergänzen</button></>}</div>}
    <div className="reletting-expose-actions">
      <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={showExpose}>Exposé als PDF ansehen</button>
      {canWrite && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={listing}>
        {data.listing ? 'Inserat aktualisieren' : 'Inserat anlegen'}</button>}
      {data.listing && <Link className="btn btn-secondary btn-sm" to={`/listings?focus_id=${encodeURIComponent(data.listing.id)}`}>
        Zum Inserat (Portalübertragung)</Link>}
    </div>
    <p className="text-muted reletting-small">Ohne angebundenes Portal die Texte unten kopieren und im Portal einfügen. Ein Inserat
      wird nur übertragen, wenn Sie es dort ausdrücklich auslösen. Fotos kommen aus den Fotos der Einheit und des Objekts.</p>
    {pdf && <div className="reletting-pdf">
      <div className="reletting-pdf-bar"><strong>Exposé</strong>
        <a className="btn btn-sm btn-secondary" href={pdf} download={`Expose-${data.unit.label}.pdf`}>Herunterladen</a>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setPdf(null)}>Schließen</button></div>
      <PdfPreview key={pdf} url={pdf} title="Exposé" />
    </div>}
    {!text ? <p role="status">Portaltexte werden erstellt …</p> : (
      <div className="reletting-blocks">
        {text.blocks.map(block => (
          <section key={block.key} className={`panel reletting-block${block.key === 'all' ? ' reletting-block-all' : ''}`}
            aria-labelledby={`reletting-block-${block.key}`}>
            <div className="panel-header reletting-panel-header"><span id={`reletting-block-${block.key}`}>{block.label}</span>
              <button type="button" className="btn btn-sm btn-ghost" disabled={!block.text} onClick={() => copy(block.label, block.text)}
                aria-label={`${block.label} kopieren`}><ClipboardCopy size={14} aria-hidden="true" /> Kopieren</button></div>
            <div className="panel-body"><pre className="reletting-text">{block.text || '—'}</pre></div>
          </section>
        ))}
      </div>
    )}
  </>;
}

// ─── Abschluss & Datenschutz ─────────────────────────────────────────────────

export function ClosingTab({ data, path, canWrite, mayWrite, onChanged, onGo }) {
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const { project } = data;
  const accepted = data.applicants.find(row => row.status === 'accepted');
  const [contractId, setContractId] = useState(data.contracts[0]?.id || '');
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const deletable = data.applicants.filter(row => row.deletable);

  const run = async action => {
    setBusy(true);
    try { await action(); } catch (failure) { toast.error(failure.message); }
    setBusy(false);
  };
  const openContract = () => {
    const start = [project.available_from, accepted?.move_in_date].filter(Boolean).sort().pop();
    holdNewEntry('/contracts', Object.fromEntries(Object.entries({
      property_id: data.property.id, unit_id: data.unit.id, tenant_id: project.tenant_id, status: 'active', start_date: start,
      deposit_amount: project.deposit_amount, persons: accepted?.household_size,
    }).filter(([, value]) => value != null)));
    navigate('/contracts');
  };
  const close = () => run(async () => {
    if (!await confirm('Projekt mit diesem Vertrag abschließen? Das Inserat wird geschlossen.', { action: 'confirm' })) return;
    onChanged(await api.post(`${path}/close`, { contract_id: contractId }));
    toast.success('Die Einheit ist vermietet, das Projekt abgeschlossen.');
  });
  const cancel = () => run(async () => {
    if (!await confirm('Neuvermietung abbrechen? Die Bewerbungen bleiben, bis Sie sie löschen.', { action: 'confirm' })) return;
    onChanged(await api.post(`${path}/cancel`, {}));
  });
  const purge = () => run(async () => {
    const names = deletable.filter(row => selected.has(row.id)).map(row => row.full_name);
    if (!await confirm(`${names.length} Bewerbung(en) mit allen Unterlagen, Besichtigungen und Notizen endgültig löschen? `
      + `(${names.join(', ')}) Das lässt sich nicht rückgängig machen.`, { action: 'delete' })) return;
    const result = onChanged(await api.post(`${path}/purge`, { lead_ids: [...selected], confirmed: true }));
    setSelected(new Set());
    toast.success(`${result.deleted} Bewerbung(en) gelöscht${result.deleted_files ? `, ${result.deleted_files} Datei(en) entfernt` : ''}.`);
  });
  const toggle = id => setSelected(previous => {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return <div className="detail-overview-grid">
    <section className="panel" aria-labelledby="reletting-tenancy">
      <div className="panel-header" id="reletting-tenancy">Mietverhältnis</div>
      <div className="panel-body reletting-closing">
        {project.status === 'closed' ? <p>Vermietet{data.tenant ? <> an <Link to={data.tenant.href}>{data.tenant.full_name}</Link></> : ''}
          {project.closed_at ? ` · abgeschlossen am ${formatDate(project.closed_at)}` : ''}.</p>
          : project.status === 'cancelled' ? <p>Die Neuvermietung wurde abgebrochen.</p>
            : !accepted ? <p className="text-muted">Noch niemand übernommen. Im <button type="button" className="link-button"
              onClick={() => onGo('compare')}>Vergleich</button> einen Bewerber als Mieter übernehmen.</p>
              : <>
                <p>Übernommen: {data.tenant ? <Link to={data.tenant.href}>{data.tenant.full_name}</Link> : accepted.full_name}</p>
                {canWrite && <button type="button" className="btn btn-primary btn-sm" onClick={openContract}>Mietvertrag anlegen</button>}
                <p className="text-muted reletting-small">Öffnet das Vertragsformular mit Einheit, Mieter, Beginn, Kaution und Personen
                  vorausgefüllt; die erste Miete ist die Miete der Einheit (= Angebot).</p>
                {data.contracts.length > 0 && canWrite && <div className="reletting-close-row">
                  <label htmlFor="reletting-contract">Vertrag</label>
                  <select id="reletting-contract" value={contractId} onChange={event => setContractId(event.target.value)}>
                    {data.contracts.map(contract => <option key={contract.id} value={contract.id}>
                      {contract.contract_number} · ab {formatDate(contract.start_date)}</option>)}
                  </select>
                  <button type="button" className="btn btn-primary btn-sm" disabled={busy || !contractId} onClick={close}>
                    Projekt abschließen (vermietet)</button>
                </div>}
              </>}
        {canWrite && <button type="button" className="btn btn-sm btn-ghost reletting-cancel" disabled={busy} onClick={cancel}>
          Neuvermietung abbrechen</button>}
      </div>
    </section>
    <section className="panel" aria-labelledby="reletting-privacy">
      <div className="panel-header" id="reletting-privacy">Datenschutz: Bewerberdaten löschen</div>
      <div className="panel-body">
        <p className="text-muted reletting-small">Abgelehnte Bewerber können Ansprüche nach dem AGG innerhalb von zwei Monaten nach der
          Absage geltend machen (§ 21 Abs. 5 AGG). Danach werden ihre Daten in der Regel nicht mehr benötigt; spätestens nach
          {` ${data.retention_days}`} Tagen markiert die App sie zum Löschen. Gelöscht werden die Bewerbung mit Unterlagen,
          Besichtigungen, Notizen und Änderungsverlauf. Der Mieterdatensatz des übernommenen Bewerbers bleibt.</p>
        {deletable.length === 0 ? <p className="text-muted">{project.status === 'open'
          ? 'Löschen lassen sich während der Vermietung nur abgesagte oder zurückgezogene Bewerbungen.'
          : 'Keine Bewerbung mehr gespeichert.'}</p> : <>
          <ul className="reletting-purge-list">
            {deletable.map(row => <li key={row.id}>
              <label><input type="checkbox" checked={selected.has(row.id)} onChange={() => toggle(row.id)} disabled={!mayWrite} />
                {' '}{row.full_name} <Badge status={row.status} />
                {row.days_since_decision != null && <span className="text-muted reletting-small"> · Absage vor {row.days_since_decision} Tagen</span>}
                {row.purge_due && <span className="badge badge-yellow">Löschung empfohlen</span>}
                {row.attachments.length > 0 && <span className="text-muted reletting-small"> · {row.attachments.length} Unterlage(n)</span>}
              </label></li>)}
          </ul>
          {mayWrite && <div className="reletting-close-row">
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => setSelected(new Set(deletable.map(row => row.id)))}>
              Alle auswählen</button>
            <button type="button" className="btn btn-sm btn-danger" disabled={busy || selected.size === 0} onClick={purge}>
              Ausgewählte endgültig löschen</button>
          </div>}
        </>}
        {project.deleted_applicants > 0 && <p className="text-muted reletting-small">Bisher gelöscht: {project.deleted_applicants} Bewerbung(en).</p>}
      </div>
    </section>
  </div>;
}
