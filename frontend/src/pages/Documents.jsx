import ChannelPanel from '../features/channels/ChannelPanel';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import CurrentDocumentViewer from '../features/documentDetail/CurrentDocumentViewer';
import { PlusIcon } from '../components/Icons';
import { Eye, FileText, Mail, Printer, Share2, Wrench } from 'lucide-react';
import { useConfirm } from '../components/ConfirmDialog';
import { useTranslation } from '../i18n';
import { PartyLink, usePartyWorkspace } from '../features/partyWorkspace/PartyWorkspace';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { documentTypeLabel, documentTypeOptions } from '../utils/documentType';
import { formatDate } from '../utils/format';
import { entityHref } from '../utils/entityLinks';
import { expiryState } from '../utils/documentExpiry';
import AktenwerkDialog from '../features/aktenwerk/AktenwerkDialog';
import { aktenwerkBulkAction, documentExchangeId, useAktenwerkReady } from '../features/aktenwerk/aktenwerkApi';
import KpiAction from '../components/KpiAction';
import MoreMenu from '../components/MoreMenu';
import DocumentWorkbench from '../features/documentWork/DocumentWorkbench';
import DocumentContentSearch from '../features/documentSearch/DocumentContentSearch';
import RetentionLockDialog from '../features/documentRetention/RetentionLockDialog';
import ShareDocumentDialog from '../features/documentShare/ShareDocumentDialog';
import { printDocuments, skippedNote } from '../features/documentShare/documentShare';
import { useToast } from '../components/Toast';
import { retentionCell, retentionOptions, retentionService } from '../features/documentRetention/retentionApi';
import { deriveDocumentAssociations, documentAssociationFields, resolveDocumentContext } from '../features/documentDetail/documentAssociations';
import AiReadingDialog from '../features/aiReading/AiReadingDialog';
import AiReadingPanel from '../features/aiReading/AiReadingPanel';
import { DOCUMENT_FORM, aiReadingApi, fillEmpty, formFromReading } from '../features/aiReading/aiReadingApi';

const CONTEXT_KEYS = ['property_id', 'unit_id', 'contract_id'];
const PLACE_KEYS = [...CONTEXT_KEYS, 'tenant_id'];

function guessDocType(filename) {
  const lower = (filename || '').toLowerCase();
  if (/mietvertrag|lease|vertrag/.test(lower)) return 'Mietvertrag';
  if (/rechnung|invoice|faktura/.test(lower)) return 'Rechnung';
  if (/nebenkosten|betriebskosten/.test(lower)) return 'Nebenkostenabrechnung';
  if (/übergabe/.test(lower)) return 'Übergabeprotokoll';
  if (/protokoll/.test(lower)) return 'Protokoll';
  if (/versicherung|police/.test(lower)) return 'Versicherung';
  if (/grundbuch/.test(lower)) return 'Grundbuchauszug';
  if (/energie/.test(lower)) return 'Energieausweis';
  if (/mahnung/.test(lower)) return 'Mahnung';
  if (/kündigung/.test(lower)) return 'Kündigung';
  if (/steuer/.test(lower)) return 'Steuerbescheid';
  return 'Sonstiges';
}

export default function Documents() {
  const [searchParams] = useSearchParams();
  // A party change starts a new workspace, including forms and in-flight upload UI.
  // Pending requests retain their original party and cannot release a newer upload.
  return <DocumentsWorkspace key={['tenant_id', ...CONTEXT_KEYS].map(key => searchParams.get(key) || '').join('|')} />;
}

function DocumentsWorkspace() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const store = useDataStore();
  const canWrite = useCanWrite('/documents');
  const auth = useAuth();
  const canOverrideRetention = auth?.role === 'eigentuemer' || auth?.role === 'verwalter';
  const [retention, setRetention] = useState(null);
  const [lockTarget, setLockTarget] = useState(null);
  const [shareTarget, setShareTarget] = useState(null);
  const toast = useToast();
  // one PDF of the chosen documents in the print dialog; the ones without a printable file are named
  const printRows = async rows => {
    const { skipped } = await printDocuments(rows.map(row => row.id));
    if (skipped.length) toast?.warning(skippedNote(skipped));
    return { failed: skipped.map(item => ({ row: rows.find(row => row.id === item.id) || { id: item.id, title: item.title }, message: item.reason })) };
  };
  const printOne = row => printRows([row]).catch(problem => toast?.error(problem.message || 'Das Dokument konnte nicht gedruckt werden.'));
  const party = usePartyWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  const tenantId = searchParams.get('tenant_id') || '';
  const contextQuery = tenantId ? '' : new URLSearchParams(CONTEXT_KEYS.filter(key => searchParams.get(key)).map(key => [key, searchParams.get(key)])).toString();
  const contextValues = Object.fromEntries(new URLSearchParams(contextQuery));
  const { items: tenants } = useEntities('tenants_all', '/tenants?include_archived=true');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [viewerFile, setViewerFile] = useState(null);
  const [postDocument, setPostDocument] = useState(null);
  const toolId = searchParams.get('tool_id');
  const closeTools = useCallback(() => setSearchParams(previous => {
    const next = new URLSearchParams(previous); next.delete('tool_id'); return next;
  }), [setSearchParams]);
  const [aktenwerkOpen, setAktenwerkOpen] = useState(false);
  const aktenwerkReady = useAktenwerkReady();
  const [uploadedUrl, setUploadedUrl] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [readingSource, setReadingSource] = useState(null);       // an uploaded file being read for the form
  const [formMarks, setFormMarks] = useState(null);
  const formReading = useRef(null);                               // the reading the open form came from
  const [filter, setFilter] = useState('all');
  const [drilldown, setDrilldown] = useState(0);
  const [pageSource, setPageSource] = useState(null);
  const openSources = value => {
    setSearchParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('suche'); return next; });
    setDrilldown(number => number + 1);
    if (tenantId) { setFilter('all'); setPageSource(value === 'all' ? null : value); if (value === 'all') setSkip(0); }
    else setFilter(value);
  };
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [partyOverview, setPartyOverview] = useState(null);
  const [documentPage, setDocumentPage] = useState(null);
  const [skip, setSkip] = useState(0);
  const [search, setSearch] = useState('');
  const [docType, setDocType] = useState('');
  const [createInitial, setCreateInitial] = useState(null);
  const overview = partyOverview?.tenant.id === tenantId ? partyOverview : null;
  const fileRef = useRef(null);
  const uploadBusy = useRef(false);
  const uploadGeneration = useRef(0);
  const exportRequest = useRef(null);
  useEffect(() => () => { uploadGeneration.current += 1; }, [tenantId]);
  useEffect(() => () => exportRequest.current?.abort(), []);

  const DOC_TYPES = useMemo(() => documentTypeOptions(t), [t]);

  const refreshData = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setLoading(true); setError(null);
    const params = new URLSearchParams({ skip: String(skip), limit: '25', q: search, document_type: docType });
    const request = tenantId
      ? Promise.all([api.get(`/tenants/${encodeURIComponent(tenantId)}/documents?${params}`, options), api.get(`/tenants/${encodeURIComponent(tenantId)}/overview`, options)])
      : api.list(`/documents${contextQuery ? `?${contextQuery}` : ''}`, options).then(items => [{ items }, null]);
    Promise.resolve().then(() => retentionService.load(options)).then(value => { if (!cancelled) setRetention(value); })
      .catch(() => { if (!cancelled) setRetention(null); });   // the list works without it; deleting still asks the server
    request.then(([page, overview]) => {
      if (!Array.isArray(page?.items) || (tenantId && (!Number.isInteger(page.total) || page.total < 0))) throw new Error('Die Dokumentquelle konnte nicht vollständig gelesen werden.');
      if (!cancelled) { setDocuments(page.items); setDocumentPage(tenantId ? page : null); setPartyOverview(overview); }
    }).catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [tenantId, skip, search, docType, revision, contextQuery]);

  // Lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c.contract_number]));
  const tenantMap = Object.fromEntries(tenants.map(person => [person.id, person.full_name]));
  if (overview) tenantMap[overview.tenant.id] = overview.tenant.full_name;
  const contractTenantMap = Object.fromEntries(contracts.map(c => [c.id, c.tenant_id]));
  const unitRecords = useMemo(() => Object.fromEntries(units.map(row => [row.id, row])), [units]);
  const contractRecords = useMemo(() => Object.fromEntries(contracts.map(row => [row.id, row])), [contracts]);

  const enrichDocument = doc => {
    const context = resolveDocumentContext(doc, unitRecords, contractRecords);
    return {
    ...doc,
    context,
    property_name: propMap[context.property_id] || '—',
    unit_label: unitMap[context.unit_id] || '—',
    contract_label: contractMap[doc.contract_id] || '—',
    party_id: doc.tenant_id || contractTenantMap[doc.contract_id] || (tenantId || null),
    party_name: tenantMap[doc.tenant_id || contractTenantMap[doc.contract_id] || tenantId] || '—',
    has_file: !!doc.file_url,
    retention: retention?.items?.[doc.id] || null,
    retention_label: retentionCell(retention?.items?.[doc.id]),
    };
  };
  const enriched = documents.map(enrichDocument);

  const loadPartyExport = async () => {
    const controller = new AbortController();
    exportRequest.current?.abort();
    exportRequest.current = controller;
    const result = [];
    const ids = new Set();
    let expectedTotal;
    try {
      let offset = 0;
      while (true) {
        const params = new URLSearchParams({ skip: String(offset), limit: '500', q: search, document_type: docType });
        const page = await api.get(`/tenants/${encodeURIComponent(tenantId)}/documents?${params}`, { signal: controller.signal });
        if (controller.signal.aborted) throw new Error('Export abgebrochen.');
        expectedTotal ??= page.total;
        if (page.total !== expectedTotal || page.items.some(item => ids.has(item.id)) || (page.has_more && !page.items.length)) {
          throw new Error('Der Dokumentbestand hat sich während des Exports geändert. Bitte starten Sie den Export erneut.');
        }
        for (const item of page.items) { ids.add(item.id); result.push(enrichDocument(item)); }
        offset += page.items.length;
        if (!page.has_more) break;
      }
      if (result.length !== expectedTotal) throw new Error('Die Dokumentliste konnte nicht vollständig exportiert werden. Bitte versuchen Sie es erneut.');
      return result;
    } finally {
      if (exportRequest.current === controller) exportRequest.current = null;
    }
  };

  const filtered = useMemo(() => {
    if (tenantId) return enriched;
    if (filter === 'all') return enriched;
    if (filter === 'no_assignment') return enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id && !d.tenant_id);
    if (filter === 'ocr_open') return enriched.filter(d => d.ocr_status === 'processing' || (!d.ocr_status && d.file_url));
    if (filter === 'with_file') return enriched.filter(d => d.file_url);
    if (filter === 'ocr_completed') return enriched.filter(d => d.ocr_status === 'completed');
    if (filter === 'expiring') return enriched.filter(d => ['expired', 'due'].includes(expiryState(d)));
    if (filter === 'retention_ended') return enriched.filter(d => d.retention?.state === 'ended');
    return enriched;
  }, [enriched, filter, tenantId]);

  // Summary stats
  const withFile = enriched.filter(d => d.file_url).length;
  const noAssignment = enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id && !d.tenant_id).length;
  const expiring = enriched.filter(d => ['expired', 'due'].includes(expiryState(d))).length;
  const retentionEnded = enriched.filter(d => d.retention?.state === 'ended').length;
  const ocrCompleted = enriched.filter(d => d.ocr_status === 'completed').length;

  const columns = [
    { key: 'title', label: t('pages.documents.columns.title') || 'Titel', filterType: 'text', link: 'document' },
    { key: 'document_type', label: t('pages.documents.columns.type') || 'Typ', filterType: 'select', render: documentTypeLabel },
    { key: 'party_name', label: 'Mieter / Partei', filterType: 'text', render: (value, row) => <PartyLink tenantId={row.party_id}>{value}</PartyLink> },
    // in a tenant's file the contract tells more than the property
    { key: 'property_name', hidden: Boolean(tenantId), label: 'Immobilie', filterType: 'text', render: (value, row) => row.context.property_id
      ? <Link to={entityHref('property', row.context.property_id)} onClick={event => event.stopPropagation()}>{value === '—' ? 'Immobilie öffnen' : value}</Link> : value },
    { key: 'unit_label', hidden: true, label: 'Einheit', filterType: 'text', render: (value, row) => row.context.unit_id
      ? <Link to={entityHref('unit', row.context.unit_id)} onClick={event => event.stopPropagation()}>{value === '—' ? 'Einheit öffnen' : value}</Link> : value },
    { key: 'contract_label', hidden: !tenantId, label: 'Vertrag', filterType: 'text', link: 'contract' },
    { key: 'document_date', label: t('pages.documents.columns.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'valid_until', label: 'Gültig bis', type: 'date', filterType: 'dateRange', render: (value, row) => {
      if (!value) return '—';
      const state = expiryState(row);
      return <span className={`document-expiry document-expiry-${state}`}>{formatDate(value)}{state === 'expired' ? ' · abgelaufen' : state === 'due' ? ' · läuft ab' : ''}</span>;
    } },
    { key: 'retention_label', hidden: true, label: 'Aufbewahrung', filterType: 'text',
      render: (value, row) => <span className={`document-retention document-retention-${row.retention?.state || 'none'}`} title={row.retention?.text}>{value}</span> },
    { key: 'tags', hidden: true, label: t('pages.documents.columns.tags') || 'Tags', filterType: 'text' },
    { key: 'has_file', hidden: true, label: t('pages.documents.columns.file') || 'Datei',
      render: v => v ? (t('pages.documents.columns.filePresent') || '✓ Vorhanden') : '—' },
    { key: 'ocr_status', hidden: true, label: t('pages.documents.columns.ocr') || 'Texterkennung', render: v => {
      if (v === 'completed') return t('pages.documents.ocr.completed') || '✓ Erkannt';
      if (v === 'processing') return t('pages.documents.ocr.processing') || '⏳ Läuft...';
      if (v === 'failed') return t('pages.documents.ocr.failed') || '✗ Fehler';
      return '—';
    }},
  ];

  const uploadFile = useCallback(async (file) => {
    if (!file || !canWrite || uploadBusy.current) return;
    uploadBusy.current = true;
    const generation = uploadGeneration.current;
    setUploading(true);
    setReadingSource(null);
    setUploadedUrl('');
    setError(null);
    try {
      const current = api.captureSession();
      const formData = new FormData();
      formData.append('file', file);
      const data = await api.upload('/files/upload?folder=documents', formData);
      current();
      if (generation !== uploadGeneration.current) return;
      if (!data.file_url) throw new Error('Der Server hat keine Datei zurückgegeben.');
      setUploadedUrl(data.file_url);
      const suggestedType = guessDocType(file.name);
      setReadingSource({ fileUrl: data.file_url, name: file.name, scope: tenantId || contextQuery, base: { ...Object.fromEntries(new URLSearchParams(contextQuery)),
        title: file.name.replace(/\.[^.]+$/, ''), file_url: data.file_url, tenant_id: tenantId || null,
        document_type: DOC_TYPES.some(type => type.value === suggestedType) ? suggestedType : 'Sonstiges' } });
    } catch (err) {
      if (generation === uploadGeneration.current) setError(err.message);
    } finally {
      uploadBusy.current = false;
      if (generation === uploadGeneration.current) setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, [canWrite, tenantId, DOC_TYPES, contextQuery]);

  const handleMultiUpload = useCallback(async (files) => {
    if (!canWrite || uploadBusy.current) return;
    uploadBusy.current = true;
    const generation = uploadGeneration.current;
    const fileList = Array.from(files);
    setUploading(true); setError(null); setUploadedUrl('');
    setUploadQueue(fileList.map(f => ({ name: f.name, status: 'pending' })));
    let current;
    let sessionValid = true;
    try {
      current = api.captureSession();
      for (let i = 0; i < fileList.length; i++) {
        current();
        if (generation !== uploadGeneration.current) break;
        setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'uploading' } : q));
        try {
          const file = fileList[i];
          const body = new FormData();
          body.append('file', file);
          body.append('title', file.name.replace(/\.[^.]+$/, ''));
          body.append('document_type', guessDocType(file.name));
          if (tenantId) body.append('tenant_id', tenantId);
          for (const [key, value] of new URLSearchParams(contextQuery)) body.append(key, value);
          await api.upload('/documents/import', body);
          current();
          if (generation === uploadGeneration.current) setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'done' } : q));
        } catch (err) {
          // A rejected owner fence stops the entire batch, including the next file.
          current();
          if (generation === uploadGeneration.current) setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'failed', error: err.message } : q));
        }
      }
    } catch (err) {
      sessionValid = false;
      if (generation === uploadGeneration.current) setError(err.message);
    } finally {
      try { current?.(); } catch { sessionValid = false; }
      uploadBusy.current = false;
      if (generation === uploadGeneration.current) { setUploading(false); if (sessionValid) refreshData(); }
      if (fileRef.current) fileRef.current.value = '';
      if (sessionValid) store?.invalidateRelated('documents');
    }
  }, [canWrite, tenantId, refreshData, store, contextQuery]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    const files = e.dataTransfer?.files;
    if (files?.length > 1) {
      handleMultiUpload(files);
    } else {
      uploadFile(files?.[0]);
    }
  }, [uploadFile, handleMultiUpload]);

  const fields = useMemo(() => [
    { key: 'title', label: t('pages.documents.form.title') || 'Titel', required: true },
    { key: 'document_type', label: t('pages.documents.form.docType') || 'Dokumententyp', type: 'select', options: DOC_TYPES },
    { key: 'document_date', label: t('pages.documents.form.date') || 'Datum', type: 'date' },
    ...documentAssociationFields({ properties, units, contracts: tenantId ? (overview?.contracts || []) : contracts, tenants, tenantId }),
    { key: 'valid_until', label: 'Gültig bis', type: 'date',
      hint: 'z. B. Energieausweis 10 Jahre, Rauchmelder- oder Wartungsnachweis 1 Jahr, Police bis zum Ablauf. Das Programm erinnert vorher mit einer Aufgabe.' },
    { key: 'reminder_days', label: 'Erinnern (Tage vorher)', type: 'number', step: '1', min: 0, max: 730, hint: 'leer: 30 Tage' },
    { key: 'retention_class', label: 'Aufbewahrung', type: 'select', options: retentionOptions(retention?.rules),
      hint: 'Solange die Frist läuft, lässt sich das Dokument nicht löschen. Automatisch: Rechnungen und Abrechnungen 8 Jahre, Briefe 6 Jahre, Verträge bis 3 Jahre nach Vertragsende.' },
    { key: 'description', label: t('pages.documents.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: t('pages.documents.form.tags') || 'Tags', placeholder: t('pages.documents.form.tagsPlaceholder') || 'kommagetrennt' },
    { key: 'file_url', type: 'hidden', required: true, default: uploadedUrl },
  ], [t, DOC_TYPES, tenantId, tenants, properties, units, contracts, overview, uploadedUrl, retention]);

  const handleSave = async (values) => {
    const data = { ...values, retention_class: values.retention_class || null };   // empty: by document type
    const saved = modal === 'create' ? await api.post('/documents', data) : await api.put(`/documents/${modal.id}`, data);
    const reading = formReading.current;
    formReading.current = null;
    if (reading) aiReadingApi.finish(reading, 'taken_over', { kind: 'document', id: saved?.id || modal.id }).catch(() => {});
    refreshData();
    if (store) store.invalidateRelated('documents');
    setUploadedUrl(''); setCreateInitial(null); setFormMarks(null);
  };

  const openForm = (initial, reading, marks) => {
    formReading.current = reading;
    setFormMarks(marks);
    setReadingSource(null);
    if (initial.id) setModal(initial);
    else { setCreateInitial(initial); setModal('create'); }
  };
  const closeForm = () => {
    const reading = formReading.current;
    formReading.current = null;
    if (reading) aiReadingApi.finish(reading, 'cancelled').catch(() => {});      // the values were not saved
    setFormMarks(null); setModal(null);
  };
  const applyReading = reading => {
    const { initial, aiMarks } = formFromReading(readingSource.base, reading, DOCUMENT_FORM, PLACE_KEYS, readingSource.name);
    if (!DOC_TYPES.some(type => type.value === initial.document_type)) initial.document_type = readingSource.base.document_type;
    openForm(initial, reading, aiMarks);
  };
  const openExisting = (item, reading) => {
    aiReadingApi.finish(reading, 'cancelled', item).catch(() => {});
    setReadingSource(null);
    navigate(item.href);
  };
  const completeExisting = async (item, reading) => {
    const record = await api.get(`/documents/${encodeURIComponent(item.id)}`);
    const { initial, aiMarks } = fillEmpty(record, reading, DOCUMENT_FORM, readingSource?.name);
    openForm(initial, reading, aiMarks);
  };

  const handleDelete = async (row) => {
    if (row.retention?.locked) { setLockTarget(row); return; }
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    try {
      await api.del(`/documents/${encodeURIComponent(row.id)}`);
      refreshData();
      if (store) store.invalidateRelated('documents');
    } catch (err) { setError(err.message); }
  };

  return (
    <div className="page documents-page">
      <div className="page-header">
        <h1>{t('pages.documents.title') || 'Dokumente'}</h1>
        <div className="page-header-actions">
          <Link className="btn btn-secondary" to="/document-queue">Dokumenteneingang & Dubletten</Link>
          <MoreMenu items={[
            { key: 'aktenwerk', label: 'Aktenwerk …', onSelect: () => setAktenwerkOpen(true),
              description: 'Verträge, Rechnungen und Belege als Paket für ein Dokumentenmanagementsystem bereitstellen oder dorthin übergeben.' },
            { key: 'teha', label: 'TEHA-Empfang und Originalhistorie', to: '/teha',
              description: 'Abrechnungsdaten und Originale vom Messdienst TEHA ansehen und übernehmen.' },
          ]} />
        </div>
      </div>
      {contextQuery && <div className="filter-chips" aria-label="Dokumentauswahl">
        <span>Dokumente für:</span>
        {contextValues.property_id && <Link to={`/properties/${encodeURIComponent(contextValues.property_id)}?tab=documents`}>{propMap[contextValues.property_id] || 'Immobilie öffnen'}</Link>}
        {contextValues.unit_id && <Link to={`/units/${encodeURIComponent(contextValues.unit_id)}`}>{unitMap[contextValues.unit_id] || 'Einheit öffnen'}</Link>}
        {contextValues.contract_id && <Link to={`/contracts?contract_id=${encodeURIComponent(contextValues.contract_id)}`}>{contractMap[contextValues.contract_id] || 'Vertrag öffnen'}</Link>}
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => setSearchParams(current => {
          const next = new URLSearchParams(current); CONTEXT_KEYS.forEach(key => next.delete(key)); return next;
        })}>Objektfilter aufheben</button>
      </div>}
      <div className="toolbar">
        <div className="documents-filter-field documents-party-field">
        <label htmlFor="document-party">Mieter / Partei</label>
        <select id="document-party" value={tenantId} disabled={uploading} onChange={event => {
          setSkip(0); setSearch(''); setDocType(''); setFilter('all'); setUploadedUrl(''); setReadingSource(null); setModal(null);
          setSearchParams(event.target.value ? { tenant_id: event.target.value } : {});
        }}>
          <option value="">Alle Dokumente</option>
          {tenants.map(person => <option key={person.id} value={person.id}>{person.full_name}{person.archived ? ' (archiviert)' : ''}</option>)}
        </select>
        </div>
        {tenantId && party && <button className="btn btn-secondary" onClick={() => party.openParty(tenantId)}>Parteienkarte öffnen</button>}
      </div>
      {aktenwerkOpen && <AktenwerkDialog ready={aktenwerkReady} onClose={() => setAktenwerkOpen(false)} />}
      {tenantId && <p className="text-muted">Dokumente von {overview?.tenant.full_name || 'dieser Partei'} und ihren Mietverträgen. Neue Uploads werden dieser Partei zugeordnet.</p>}
      {searchParams.get('create') === '1' && canWrite && <p role="status">Wählen Sie unten eine oder mehrere Dateien. Bei einer Datei können Sie die Angaben vor dem Speichern prüfen.</p>}
      {error && <div role="alert" className="alert alert-error">{error} <button className="btn btn-sm btn-secondary" onClick={refreshData}>Erneut laden</button></div>}

      {/* Summary cards */}
      {!loading && !error && <div className="kpi-row">
        <KpiAction label="Gesamt" value={documentPage?.total ?? enriched.length} onClick={() => openSources('all')} />
        <KpiAction label={`Mit Datei${tenantId ? ' auf dieser Seite' : ''}`} value={withFile} onClick={() => openSources('with_file')} />
        <KpiAction label={`Texterkennung abgeschlossen${tenantId ? ' auf dieser Seite' : ''}`} value={ocrCompleted} onClick={() => openSources('ocr_completed')} />
        {noAssignment > 0 && <KpiAction label={`Ohne Zuordnung${tenantId ? ' auf dieser Seite' : ''}`} value={noAssignment} color="var(--warning)" onClick={() => openSources('no_assignment')} />}
        {expiring > 0 && !tenantId && <KpiAction label="Läuft ab oder abgelaufen" value={expiring} color="var(--warning)" onClick={() => openSources('expiring')} />}
        {retentionEnded > 0 && !tenantId && <KpiAction label="Aufbewahrung abgelaufen" value={retentionEnded} onClick={() => openSources('retention_ended')} />}
      </div>}

      {!tenantId && <DocumentContentSearch onOpen={setViewerFile} places={propMap} canWrite={canWrite} scope={contextValues} />}

      {/* Filter tabs */}
      {!tenantId && <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'no_assignment', label: 'Ohne Zuordnung' },
          { key: 'ocr_open', label: 'Texterkennung offen' },
          { key: 'with_file', label: 'Mit Datei' },
          { key: 'ocr_completed', label: 'Texterkennung abgeschlossen' },
          { key: 'expiring', label: 'Läuft ab oder abgelaufen' },
          { key: 'retention_ended', label: 'Aufbewahrung abgelaufen' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => openSources(f.key)}>
            {f.label}
          </button>
        ))}
      </div>}
      {tenantId && <div className="toolbar" style={{ flexWrap: 'wrap', marginBottom: '1rem' }}>
        <div className="documents-filter-field">
        <label htmlFor="party-document-search">Dokumente durchsuchen</label>
        <input id="party-document-search" type="search" placeholder="Titel, Beschreibung oder Schlagwort" value={search}
          onChange={event => { setSearch(event.target.value); setSkip(0); }} />
        </div>
        <div className="documents-filter-field">
        <label htmlFor="party-document-type">Dokumententyp</label>
        <select id="party-document-type" value={docType} onChange={event => { setDocType(event.target.value); setSkip(0); }}>
          <option value="">Alle Typen</option>
          {(overview?.document_types || []).map(type => <option key={type} value={type}>{documentTypeLabel(type)}</option>)}
        </select>
        </div>
      </div>}

      {/* Upload zone */}
      {canWrite && <div style={{ marginBottom: '1rem' }}>
        <div
          className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          role="button" tabIndex={0} aria-label="Dokumente hochladen" aria-disabled={uploading}
          onClick={() => { if (!uploading) fileRef.current?.click(); }}
          onKeyDown={event => { if (!uploading && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); fileRef.current?.click(); } }}
        >
          <input
            ref={fileRef}
            type="file"
            multiple
            disabled={uploading}
            aria-label="Dokumentdateien wählen"
            onClick={event => event.stopPropagation()}
            style={{ display: 'none' }}
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.doc,.docx,.xls,.xlsx"
            onChange={e => {
              const files = e.target.files;
              if (files?.length > 1) handleMultiUpload(files);
              else uploadFile(files?.[0]);
            }}
          />
          <PlusIcon size={24} />
          <span>{uploading ? (t('pages.documents.upload.uploading') || 'Wird hochgeladen...') : (t('pages.documents.upload.dropHint') || 'Dokumente hierher ziehen oder klicken (mehrere Dateien möglich)')}</span>
          <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
            {t('pages.documents.upload.supportedFormats') || 'Unterstützt: PDF, PNG, JPG, TIFF, DOC, DOCX, XLS, XLSX — bei Bildern und PDFs wird der Text automatisch erkannt'}
          </span>
          <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
            Eine Datei: Angaben prüfen und speichern. Mehrere Dateien: Jede Datei wird als eigenes Dokument mit ihrem Dateinamen importiert.
          </span>
          {uploadedUrl && <span className="text-muted">{t('pages.documents.upload.uploaded') || 'Hochgeladen:'} {uploadedUrl}</span>}
        </div>
      </div>}

      {/* Upload queue */}
      {uploadQueue.length > 0 && (
        <div role="status" style={{ marginBottom: '0.5rem' }}>
          {uploadQueue.map((q, i) => (
            <div key={i} className="text-muted" style={{ fontSize: 'var(--text-sm)' }}>
              {q.status === 'uploading' ? '⏳' : q.status === 'done' ? '✓' : q.status === 'failed' ? '✗' : '○'} {q.name}
              {q.status === 'done' && ' — Gespeichert'}
              {q.error && <span className="text-red"> — {q.error}. Vor erneutem Import prüfen, ob die Datei bereits gespeichert wurde.</span>}
            </div>
          ))}
        </div>
      )}

      {loading && <p role="status">Dokumente werden geladen …</p>}
      {tenantId && pageSource && !loading && !error && <section aria-label="Kennzahlquelle auf dieser Dokumentseite" className="panel">
        <div className="panel-header">{pageSource === 'with_file' ? 'Mit Datei' : pageSource === 'ocr_completed' ? 'Texterkennung abgeschlossen' : 'Ohne Zuordnung'} · Quelle auf dieser Seite
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPageSource(null)}>Quellansicht schließen</button></div>
        <DataTable title="Dokumente auf dieser Seite" settingsKey="documents-page-source" columns={columns}
          data={enriched.filter(row => pageSource === 'with_file' ? Boolean(row.file_url) : pageSource === 'ocr_completed' ? row.ocr_status === 'completed' : !row.property_id && !row.unit_id && !row.contract_id && !row.tenant_id)}
          drilldownKey={drilldown} onRowClick={row => row.file_url && setViewerFile(row)} />
      </section>}
      {!loading && !error && <DataTable
        title={t('pages.documents.title') || 'Dokumente'}
        columns={columns}
        data={filtered}
        drilldownKey={drilldown}
        serverPaged={Boolean(tenantId)}
        viewAnchor={tenantId ? { kind: 'tenant', id: tenantId } : undefined}
        viewConfig={tenantId ? { search, column_filters: { document_type: docType, document_filter: filter } } : { column_filters: { document_filter: filter } }}
        onApplyView={tenantId ? config => {
          setSearch(typeof config.search === 'string' ? config.search : '');
          setDocType(typeof config.column_filters?.document_type === 'string' ? config.column_filters.document_type : '');
          setFilter('all'); setPageSource(null);
          setSkip(0);
        } : config => setFilter(['all', 'no_assignment', 'ocr_open', 'with_file', 'ocr_completed', 'expiring'].includes(config.column_filters?.document_filter) ? config.column_filters.document_filter : 'all')}
        loadExportData={tenantId ? loadPartyExport : undefined}
        onAdd={() => fileRef.current?.click()}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => row.file_url && setViewerFile(row)}
        rowActions={row => [...(row.file_url ? [{ label: 'Dokument ansehen', icon: <Eye size={15} aria-hidden="true" />, onClick: () => setViewerFile(row) },
          { label: 'Drucken', icon: <Printer size={15} aria-hidden="true" />, onClick: () => printOne(row) },
          { label: 'Teilen', icon: <Share2 size={15} aria-hidden="true" />, onClick: () => setShareTarget(row) }] : []),
          { label: 'Dokumentseite öffnen', icon: <FileText size={15} aria-hidden="true" />, onClick: () => navigate(`/documents/${encodeURIComponent(row.id)}`) },
          ...(row.file_url ? [{ label: 'Brief und Frankatur', icon: <Mail size={15} aria-hidden="true" />, onClick: () => setPostDocument(row) },
          { label: 'Dokumentwerkzeuge', icon: <Wrench size={15} aria-hidden="true" />, onClick: () => setSearchParams(previous => {
            const next = new URLSearchParams(previous); next.set('tool_id', row.id); return next;
          }) }] : [])]}
        rowName={row => row.title || row.id}
        bulkActions={[{ key: 'print', label: 'Drucken', applies: row => Boolean(row.file_url), runAll: printRows },
          ...(aktenwerkReady ? [aktenwerkBulkAction(row => (row.file_url ? documentExchangeId(row.id) : null))] : [])]}
      />}
      {tenantId && documentPage && !loading && !error && <nav aria-label="Dokumentseiten" className="toolbar" style={{ flexWrap: 'wrap', justifyContent: 'space-between' }}>
        <button className="btn btn-secondary" disabled={skip === 0} onClick={() => setSkip(value => Math.max(0, value - 25))}>Vorherige Dokumente</button>
        <span>{documentPage.total === 0 ? 'Keine Dokumente' : `${skip + 1}–${skip + documents.length} von ${documentPage.total}`}</span>
        <button className="btn btn-secondary" disabled={!documentPage.has_more} onClick={() => setSkip(value => value + 25)}>Weitere Dokumente</button>
      </nav>}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Dokument erstellen' : 'Dokument bearbeiten'}
          fields={fields}
          derive={deriveDocumentAssociations(units, tenantId ? (overview?.contracts || []) : contracts)}
          initial={modal === 'create' ? createInitial : modal}
          onSave={handleSave}
          onClose={closeForm}
          aiMarks={formMarks}
        />
      )}
      {readingSource && readingSource.scope === (tenantId || contextQuery) && <AiReadingDialog title="Dokument einlesen" onClose={() => setReadingSource(null)}>
        <AiReadingPanel surface="document" autoStart source={{ fileUrl: readingSource.fileUrl, name: readingSource.name }}
          params={Object.fromEntries(PLACE_KEYS.map(key => [key, readingSource.base[key] || null]).filter(([, value]) => value))}
          title="Was steht im Dokument?" onApply={applyReading} onSkip={() => openForm(readingSource.base, null, null)}
          onCancel={() => setReadingSource(null)} onOpenExisting={openExisting} onUpdateExisting={completeExisting} />
      </AiReadingDialog>}
      {lockTarget?.retention && <RetentionLockDialog document={lockTarget} retention={lockTarget.retention}
        canOverride={canWrite && canOverrideRetention} onClose={() => setLockTarget(null)}
        onDeleted={() => { setLockTarget(null); refreshData(); if (store) store.invalidateRelated('documents'); }} />}
      {viewerFile && <CurrentDocumentViewer key={viewerFile.id} document={viewerFile} onClose={() => setViewerFile(null)} />}
      {shareTarget && <ShareDocumentDialog key={shareTarget.id} document={shareTarget} partyId={shareTarget.party_id} onClose={() => setShareTarget(null)} />}
      {postDocument && <section className="panel" aria-label="Brief und Frankatur">
        <button type="button" className="btn btn-secondary" onClick={() => setPostDocument(null)}>Briefvorbereitung schließen</button>
        <ChannelPanel key={postDocument.id} sourceId={postDocument.id} mode="post" />
      </section>}
      {toolId && <DocumentWorkbench key={toolId} documentId={toolId} onClose={closeTools} />}
    </div>
  );
}
