import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Download, Eye, FileUp, Mail, Pencil, Trash2, Wrench } from 'lucide-react';
import { useTranslation } from '../i18n';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { useDataStore } from '../contexts/DataStoreContext';
import { useConfirm } from '../components/ConfirmDialog';
import FormModal from '../components/FormModal';
import FileViewer from '../components/FileViewer';
import PdfPreview from '../components/PdfPreview';
import RelatedPageLinks from '../components/RelatedPageLinks';
import ChannelPanel from '../features/channels/ChannelPanel';
import DocumentWorkbench from '../features/documentWork/DocumentWorkbench';
import { downloadVersion } from '../features/documentWork/documentWorkApi';
import RetentionLockDialog from '../features/documentRetention/RetentionLockDialog';
import { retentionCell, retentionOptions, retentionService } from '../features/documentRetention/retentionApi';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import { fileKind, resolveFileUrl } from '../features/partyWorkspace/files';
import {
  TEXT_SOURCES, documentDetailService, previewKind, shownFilename, sizeLabel, uploadNewVersion, versionLabel,
} from '../features/documentDetail/documentDetailApi';
import { documentTypeLabel, documentTypeOptions } from '../utils/documentType';
import { expiryState } from '../utils/documentExpiry';
import { entityHref } from '../utils/entityLinks';
import { formatDate, formatDateTime } from '../utils/format';
import '../features/documentDetail/documentDetail.css';
import './propertyDossier.css';

const PREVIEW_LIMIT = 20 * 1024 * 1024;     // larger versions are downloaded, not drawn on the page
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.tiff,.tif,.doc,.docx,.xls,.xlsx,.odt,.ods,.txt,.csv';

export default function DocumentDetail({ service = documentDetailService }) {
  const { documentId } = useParams();
  return <DocumentPage key={documentId} id={documentId} service={service} />;
}

function DocumentPage({ id, service }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const store = useDataStore();
  const auth = useAuth();
  const canWrite = useCanWrite('/documents');
  const [details, setDetails] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [older, setOlder] = useState({ items: [], next: null, busy: false });
  const [panel, setPanel] = useState(null);         // edit | viewer | tools | post | lock
  const [retentionRules, setRetentionRules] = useState(null);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    service.load(id, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setDetails(value); setOlder({ items: [], next: value.versions?.next_before ?? null, busy: false }); } })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Das Dokument konnte nicht geladen werden.'); });
    return () => controller.abort();
  }, [id, service, revision]);

  useEffect(() => {
    if (panel !== 'edit' || retentionRules) return undefined;
    const controller = new AbortController();
    retentionService.load({ signal: controller.signal }).then(value => setRetentionRules(value.rules)).catch(() => {});
    return () => controller.abort();
  }, [panel, retentionRules]);

  const fields = useMemo(() => [
    { key: 'title', label: t('pages.documents.form.title') || 'Titel', required: true },
    { key: 'document_type', label: t('pages.documents.form.docType') || 'Dokumententyp', type: 'select', options: documentTypeOptions(t) },
    { key: 'document_date', label: t('pages.documents.form.date') || 'Datum', type: 'date' },
    { key: 'valid_until', label: 'Gültig bis', type: 'date', hint: 'Das Programm erinnert vorher mit einer Aufgabe.' },
    { key: 'reminder_days', label: 'Erinnern (Tage vorher)', type: 'number', step: '1', min: 0, max: 730, hint: 'leer: 30 Tage' },
    { key: 'retention_class', label: 'Aufbewahrung', type: 'select', options: retentionOptions(retentionRules) },
    { key: 'description', label: t('pages.documents.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: t('pages.documents.form.tags') || 'Tags', placeholder: t('pages.documents.form.tagsPlaceholder') || 'kommagetrennt' },
  ], [t, retentionRules]);

  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}</div>
    <div className="dossier-navigation">
      <button type="button" className="btn btn-secondary" onClick={reload}>Erneut laden</button>
      <Link className="btn btn-secondary" to="/documents">Zur Dokumentliste</Link>
    </div></div>;
  if (!details) return <div className="page-loading" role="status">Dokument wird geladen …</div>;

  const { document, places, retention, text } = details;
  const versions = [...(details.versions?.items || []), ...older.items];
  const head = versions[0] || null;
  const unbound = details.versions?.unavailable || null;     // versions need a property or contract
  const expiry = expiryState(document);
  const run = async action => {
    setActionError(null);
    try { await action(); } catch (failure) { setActionError(failure.message || 'Die Aktion ist fehlgeschlagen.'); }
  };
  const changed = () => { reload(); store?.invalidateRelated?.('documents'); };
  const loadOlder = () => run(async () => {
    setOlder(current => ({ ...current, busy: true }));
    try {
      const page = await service.olderVersions(id, older.next);
      setOlder(current => ({ items: [...current.items, ...page.items], next: page.next_before ?? null, busy: false }));
    } finally { setOlder(current => ({ ...current, busy: false })); }
  });
  const remove = () => run(async () => {
    if (retention?.locked) { setPanel('lock'); return; }
    if (confirm && !(await confirm(`"${document.title}" ${t('modals.confirmDelete.body')}`, { action: 'delete' }))) return;
    await service.remove(id);
    store?.invalidateRelated?.('documents');
    navigate('/documents');
  });
  const related = [
    document.property_id && { to: entityHref('property', document.property_id), label: `Immobilie: ${places.property || 'öffnen'}` },
    document.unit_id && { to: entityHref('unit', document.unit_id), label: `Einheit: ${places.unit || 'öffnen'}` },
    document.contract_id && { to: entityHref('contract', document.contract_id), label: `Vertrag: ${places.contract || 'öffnen'}` },
  ].filter(Boolean);

  return (
    <div className="page property-dossier document-dossier">
      <div className="detail-header">
        <Link className="btn btn-sm btn-secondary" to="/documents">← Zur Dokumentliste</Link>
        <div className="detail-title">
          <h1>{document.title}</h1>
          <span className="text-muted">{documentTypeLabel(document.document_type) || 'Dokument'}{document.document_date ? ` · ${formatDate(document.document_date)}` : ''}
            {head ? ` · Fassung ${head.number}` : ''}</span>
        </div>
        <div className="dossier-actions document-dossier-actions">
          {document.file_url && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPanel('viewer')}><Eye size={15} aria-hidden="true" /> Hochgeladene Datei ansehen</button>}
          {canWrite && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPanel('edit')}><Pencil size={15} aria-hidden="true" /> Angaben bearbeiten</button>}
          {(document.file_url || head) && !unbound && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPanel('tools')}><Wrench size={15} aria-hidden="true" /> Dokumentwerkzeuge</button>}
          {(document.file_url || head) && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPanel('post')}><Mail size={15} aria-hidden="true" /> Brief und Frankatur</button>}
        </div>
      </div>
      <RelatedPageLinks items={related} />
      {actionError && <div role="alert" className="alert alert-error">{actionError}</div>}

      <div className="document-dossier-grid">
        <section className="panel document-preview-panel" aria-label="Vorschau">
          <div className="panel-header">Vorschau{head ? ` · Fassung ${head.number}` : document.file_url ? ' · hochgeladene Datei' : ''}</div>
          <div className="panel-body"><DocumentPreview key={head?.id || document.file_url || 'none'} id={id} head={head} document={document} service={service} /></div>
        </section>

        <div className="document-dossier-side">
          <section className="panel" aria-label="Angaben">
            <div className="panel-header">Angaben</div>
            <div className="panel-body">
              <div className="detail-field"><span>Typ:</span> {documentTypeLabel(document.document_type) || '—'}</div>
              <div className="detail-field"><span>Datum:</span> {formatDate(document.document_date)}</div>
              <div className="detail-field"><span>Gültig bis:</span> {document.valid_until
                ? <span className={`document-expiry document-expiry-${expiry}`}>{formatDate(document.valid_until)}{expiry === 'expired' ? ' · abgelaufen' : expiry === 'due' ? ' · läuft ab' : ''}
                  {` · Erinnerung ${Number.isInteger(document.reminder_days) ? document.reminder_days : 30} Tage vorher`}</span>
                : '—'}</div>
              <div className="detail-field"><span>Schlagwörter:</span> {document.tags || '—'}</div>
              {document.description && <p className="document-dossier-description">{document.description}</p>}
            </div>
          </section>

          <section className="panel" aria-label="Zuordnung">
            <div className="panel-header">Zuordnung</div>
            <div className="panel-body">
              <div className="detail-field"><span>Immobilie:</span> {document.property_id ? <Link to={entityHref('property', document.property_id)}>{places.property || 'Immobilie'}</Link> : '—'}</div>
              <div className="detail-field"><span>Einheit:</span> {document.unit_id ? <Link to={entityHref('unit', document.unit_id)}>{places.unit || 'Einheit'}</Link> : '—'}</div>
              <div className="detail-field"><span>Vertrag:</span> {document.contract_id ? <Link to={entityHref('contract', document.contract_id)}>{places.contract || 'Vertrag'}</Link> : '—'}</div>
              <div className="detail-field"><span>Mieter / Partei:</span> {document.tenant_id ? <PartyLink tenantId={document.tenant_id}>{places.tenant || 'Partei öffnen'}</PartyLink> : '—'}</div>
              {!document.property_id && !document.unit_id && !document.contract_id && !document.tenant_id &&
                <p className="text-muted document-dossier-note">Noch keiner Immobilie, Einheit, keinem Vertrag und keiner Partei zugeordnet.</p>}
            </div>
          </section>

          <section className="panel" aria-label="Aufbewahrung">
            <div className="panel-header">Aufbewahrung</div>
            <div className="panel-body">
              <div className="detail-field"><span>Frist:</span> <span className={`document-retention document-retention-${retention?.state || 'none'}`}>{retentionCell(retention)}</span></div>
              {retention && <p className="document-dossier-note">{retention.text}{retention.basis ? ` Grundlage: ${retention.basis}.` : ''}
                {retention.chosen ? ' Im Dokument festgelegt.' : ' Nach dem Dokumenttyp.'}</p>}
              {retention?.locked && <p className="text-muted document-dossier-note">Solange die Frist läuft, lässt sich das Dokument nicht löschen.</p>}
            </div>
          </section>
        </div>
      </div>

      <section className="panel" aria-label="Fassungen">
        <div className="panel-header">Fassungen</div>
        <div className="panel-body">
          {unbound && <p className="text-muted">{unbound} Fassungen und die Dokumentwerkzeuge gibt es, sobald das Dokument einer Immobilie oder einem Vertrag zugeordnet ist.</p>}
          {!versions.length && !unbound && <p className="text-muted">{document.file_url
            ? 'Bisher gibt es nur die hochgeladene Datei. Wer eine neue Fassung hochlädt oder das Dokument mit den Werkzeugen bearbeitet, archiviert sie vorher als Fassung 1.'
            : 'Dieses Dokument hat noch keine Datei.'}</p>}
          {versions.length > 0 && <ol className="document-versions" aria-label="Archivierte Fassungen">
            {versions.map((version, index) => <li key={version.id}>
              <div>
                <strong>Fassung {version.number}</strong>{index === 0 && <span className="badge badge-blue">aktuell</span>}
                <span className="text-muted"> · {formatDateTime(version.created_at)}</span>
                <div className="document-version-comment">{version.comment || versionLabel(version)}</div>
                <div className="text-muted document-version-file">{shownFilename(version.filename)} · {sizeLabel(version.size_bytes)}</div>
              </div>
              <button type="button" className="btn btn-sm btn-secondary" aria-label={`Fassung ${version.number} herunterladen`}
                onClick={() => run(() => downloadVersion(id, version.id, shownFilename(version.filename)))}><Download size={15} aria-hidden="true" /> Herunterladen</button>
            </li>)}
          </ol>}
          {older.next != null && <button type="button" className="btn btn-sm btn-secondary" disabled={older.busy} onClick={loadOlder}>Ältere Fassungen laden</button>}
          {canWrite && (document.file_url || head) && !unbound && <NewVersionForm id={id} service={service} onUploaded={changed} />}
        </div>
      </section>

      {text && <section className="panel" aria-label="Gelesener Text">
        <div className="panel-header">Gelesener Text für die Suche</div>
        <div className="panel-body">
          <p className="text-muted document-dossier-note">{TEXT_SOURCES[text.source] || text.source} · {text.characters.toLocaleString('de-DE')} Zeichen · gelesen {formatDateTime(text.indexed_at)}
            {text.source_ref?.startsWith('version:') ? ` · aus Fassung ${versions.find(item => `version:${item.id}` === text.source_ref)?.number ?? 'des Archivs'}` : ''}</p>
          {text.excerpt ? <details><summary>Text anzeigen{text.characters > text.excerpt.length ? ' (Anfang)' : ''}</summary><pre className="document-dossier-text">{text.excerpt}</pre></details>
            : <p className="text-muted">Aus dieser Datei ließ sich kein Text lesen.</p>}
        </div>
      </section>}

      {canWrite && <div className="document-dossier-danger">
        <button type="button" className="btn btn-sm btn-danger" disabled={versions.length > 0}
          title={versions.length > 0 ? 'Dokumente mit archivierten Fassungen bleiben erhalten.' : undefined}
          onClick={remove}><Trash2 size={15} aria-hidden="true" /> Dokument löschen</button>
        {versions.length > 0 && <span className="text-muted document-dossier-note"> Dokumente mit archivierten Fassungen lassen sich nicht löschen.</span>}
      </div>}

      {panel === 'edit' && <FormModal title="Dokument bearbeiten" fields={fields} initial={document} onClose={() => setPanel(null)}
        onSave={async values => {
          const payload = Object.fromEntries(fields.map(field => [field.key, values[field.key] === '' ? null : values[field.key] ?? null]));
          await service.patch(id, { ...payload, title: values.title });
          changed();
        }} />}
      {panel === 'viewer' && document.file_url && <FileViewer fileUrl={document.file_url} title={document.title} onClose={() => setPanel(null)} />}
      {panel === 'tools' && <DocumentWorkbench documentId={id} onClose={() => { setPanel(null); changed(); }} />}
      {panel === 'post' && <section className="panel" aria-label="Brief und Frankatur">
        <button type="button" className="btn btn-secondary" onClick={() => setPanel(null)}>Briefvorbereitung schließen</button>
        <ChannelPanel sourceId={id} mode="post" />
      </section>}
      {panel === 'lock' && retention && <RetentionLockDialog document={document} retention={retention}
        canOverride={canWrite && ['eigentuemer', 'verwalter'].includes(auth?.role)} onClose={() => setPanel(null)}
        onDeleted={() => { store?.invalidateRelated?.('documents'); navigate('/documents'); }} />}
    </div>
  );
}

function DocumentPreview({ id, head, document, service }) {
  const [state, setState] = useState({ url: null, error: null, wanted: Boolean(head && head.size_bytes <= PREVIEW_LIMIT) });
  const kind = head ? previewKind(head.media_type, head.filename) : fileKind(document.file_url);
  const headId = head?.id;
  useEffect(() => {
    if (!headId || !state.wanted || kind === 'other') return undefined;
    const controller = new AbortController();
    let url = null;
    service.versionBlob(id, headId, { signal: controller.signal })
      .then(blob => { if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setState(current => ({ ...current, url, error: null })); } })
      .catch(failure => { if (!controller.signal.aborted) setState(current => ({ ...current, error: failure.message || 'Die Fassung konnte nicht geladen werden.' })); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [id, headId, kind, service, state.wanted]);

  if (!head && !document.file_url) return <p className="text-muted">Keine Datei vorhanden.</p>;
  if (kind === 'other') return <p className="text-muted">Für dieses Dateiformat gibt es keine Vorschau. {head ? 'Die Fassung lässt sich unten herunterladen' : 'Die Datei lässt sich über „Hochgeladene Datei ansehen“ öffnen'}{head?.media_type?.includes('word') || /\.docx?$/i.test(head?.filename || '') ? ' oder in den Dokumentwerkzeugen bearbeiten.' : '.'}</p>;
  if (!head) {
    const url = resolveFileUrl(document.file_url);
    return kind === 'pdf' ? <PdfPreview url={url} title={document.title} />
      : <p className="text-muted">Bilder öffnen Sie über „Hochgeladene Datei ansehen“.</p>;
  }
  if (!state.wanted) return <p className="text-muted">Die Fassung ist {sizeLabel(head.size_bytes)} groß. <button type="button" className="btn btn-sm btn-secondary" onClick={() => setState(current => ({ ...current, wanted: true }))}>Vorschau trotzdem laden</button></p>;
  if (state.error) return <p role="alert" className="text-red">{state.error}</p>;
  if (!state.url) return <p role="status" className="text-muted">Vorschau wird geladen …</p>;
  return kind === 'pdf' ? <PdfPreview url={state.url} title={document.title} />
    : <img className="document-preview-image" src={state.url} alt={`Fassung ${head.number} von ${document.title}`} />;
}

function NewVersionForm({ id, service, onUploaded }) {
  const [file, setFile] = useState(null);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const attempt = useRef(null);
  const input = useRef(null);
  const submit = async event => {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true); setMessage(null);
    try {
      const result = await uploadNewVersion(service, id, file, comment.trim(), attempt);
      setMessage({ ok: true, text: `Gespeichert als Fassung ${result.version.number}. Die vorige Fassung bleibt im Archiv.` });
      setFile(null); setComment('');
      if (input.current) input.current.value = '';
      onUploaded();
    } catch (failure) {
      setMessage({ ok: false, text: failure.message || 'Die neue Fassung konnte nicht gespeichert werden.' });
    } finally { setBusy(false); }
  };
  return <form className="document-version-form" onSubmit={submit} aria-label="Neue Fassung hochladen">
    <h3><FileUp size={16} aria-hidden="true" /> Neue Fassung hochladen</h3>
    <p className="text-muted document-dossier-note">Für eine korrigierte oder neu eingescannte Datei: Sie wird die aktuelle Fassung dieses Dokuments, statt als zweites Dokument abgelegt zu werden. Ältere Fassungen bleiben unverändert erhalten.</p>
    <label htmlFor={`version-file-${id}`}>Datei</label>
    <input ref={input} id={`version-file-${id}`} type="file" accept={ACCEPT} disabled={busy}
      onChange={event => { setFile(event.target.files?.[0] || null); setMessage(null); }} />
    <label htmlFor={`version-comment-${id}`}>Was hat sich geändert? (optional)</label>
    <input id={`version-comment-${id}`} type="text" maxLength={300} value={comment} disabled={busy}
      placeholder="z. B. korrigierte Rechnungsnummer" onChange={event => setComment(event.target.value)} />
    <div><button type="submit" className="btn btn-primary btn-sm" disabled={!file || busy}>{busy ? 'Wird gespeichert …' : 'Als neue Fassung speichern'}</button></div>
    {message && <p role={message.ok ? 'status' : 'alert'} className={message.ok ? 'text-green' : 'text-red'}>{message.text}</p>}
  </form>;
}
