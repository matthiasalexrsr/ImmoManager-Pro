import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import FileViewer from '../components/FileViewer';
import { PlusIcon } from '../components/Icons';
import { useConfirm } from '../components/ConfirmDialog';
import { useTranslation } from '../i18n';
import { PartyLink, usePartyWorkspace } from '../features/partyWorkspace/PartyWorkspace';
import { useCanWrite } from '../contexts/AuthContext';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

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
  return <DocumentsWorkspace key={searchParams.get('tenant_id') || 'all'} />;
}

function DocumentsWorkspace() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const canWrite = useCanWrite('/documents');
  const party = usePartyWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  const tenantId = searchParams.get('tenant_id') || '';
  const { items: tenants } = useEntities('tenants_all', '/tenants?include_archived=true');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [viewerFile, setViewerFile] = useState(null);
  const [uploadedUrl, setUploadedUrl] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [ocrResult, setOcrResult] = useState(null);
  const [filter, setFilter] = useState('all');
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

  const DOC_TYPES = useMemo(() => [
    { value: 'Mietvertrag', label: t('pages.documents.docTypes.mietvertrag') || 'Mietvertrag' },
    { value: 'Rechnung', label: t('pages.documents.docTypes.rechnung') || 'Rechnung' },
    { value: 'Nebenkostenabrechnung', label: t('pages.documents.docTypes.nebenkostenabrechnung') || 'Nebenkostenabrechnung' },
    { value: 'Protokoll', label: t('pages.documents.docTypes.protokoll') || 'Protokoll' },
    { value: 'Versicherung', label: t('pages.documents.docTypes.versicherung') || 'Versicherung' },
    { value: 'Grundbuchauszug', label: t('pages.documents.docTypes.grundbuchauszug') || 'Grundbuchauszug' },
    { value: 'Energieausweis', label: t('pages.documents.docTypes.energieausweis') || 'Energieausweis' },
    { value: 'Betriebskostenabrechnung', label: t('pages.documents.docTypes.betriebskostenabrechnung') || 'Betriebskostenabrechnung' },
    { value: 'Mahnung', label: t('pages.documents.docTypes.mahnung') || 'Mahnung' },
    { value: 'Kündigung', label: t('pages.documents.docTypes.kuendigung') || 'Kündigung' },
    { value: 'Übergabeprotokoll', label: t('pages.documents.docTypes.uebergabeprotokoll') || 'Übergabeprotokoll' },
    { value: 'Handwerkerrechnung', label: t('pages.documents.docTypes.handwerkerrechnung') || 'Handwerkerrechnung' },
    { value: 'Steuerbescheid', label: t('pages.documents.docTypes.steuerbescheid') || 'Steuerbescheid' },
    { value: 'Sonstiges', label: t('pages.documents.docTypes.sonstiges') || 'Sonstiges' },
  ], [t]);

  const refreshData = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setLoading(true); setError(null);
    const params = new URLSearchParams({ skip: String(skip), limit: '25', q: search, document_type: docType });
    const request = tenantId
      ? Promise.all([api.get(`/tenants/${encodeURIComponent(tenantId)}/documents?${params}`, options), api.get(`/tenants/${encodeURIComponent(tenantId)}/overview`, options)])
      : api.list('/documents', options).then(items => [{ items }, null]);
    request.then(([page, overview]) => {
      if (!cancelled) { setDocuments(page.items); setDocumentPage(tenantId ? page : null); setPartyOverview(overview); }
    }).catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [tenantId, skip, search, docType, revision]);

  // Lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c.contract_number]));
  const tenantMap = Object.fromEntries(tenants.map(person => [person.id, person.full_name]));
  if (overview) tenantMap[overview.tenant.id] = overview.tenant.full_name;
  const contractTenantMap = Object.fromEntries(contracts.map(c => [c.id, c.tenant_id]));

  const enrichDocument = doc => ({
    ...doc,
    property_name: propMap[doc.property_id] || '—',
    unit_label: unitMap[doc.unit_id] || '—',
    contract_label: contractMap[doc.contract_id] || '—',
    party_id: doc.tenant_id || contractTenantMap[doc.contract_id] || (tenantId || null),
    party_name: tenantMap[doc.tenant_id || contractTenantMap[doc.contract_id] || tenantId] || '—',
    has_file: !!doc.file_url,
  });
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
    if (filter === 'all') return enriched;
    if (filter === 'no_assignment') return enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id && !d.tenant_id);
    if (filter === 'ocr_open') return enriched.filter(d => d.ocr_status === 'processing' || (!d.ocr_status && d.file_url));
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const withFile = enriched.filter(d => d.file_url).length;
  const noAssignment = enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id && !d.tenant_id).length;
  const ocrCompleted = enriched.filter(d => d.ocr_status === 'completed').length;

  const columns = [
    { key: 'title', label: t('pages.documents.columns.title') || 'Titel', filterType: 'text' },
    { key: 'document_type', label: t('pages.documents.columns.type') || 'Typ', filterType: 'select' },
    { key: 'party_name', label: 'Mieter / Partei', filterType: 'text', render: (value, row) => <PartyLink tenantId={row.party_id}>{value}</PartyLink> },
    { key: 'property_name', label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: 'Einheit', filterType: 'text' },
    { key: 'contract_label', label: 'Vertrag', filterType: 'text' },
    { key: 'document_date', label: t('pages.documents.columns.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'tags', label: t('pages.documents.columns.tags') || 'Tags', filterType: 'text' },
    { key: 'has_file', label: t('pages.documents.columns.file') || 'Datei',
      render: v => v ? (t('pages.documents.columns.filePresent') || '✓ Vorhanden') : '—' },
    { key: 'ocr_status', label: t('pages.documents.columns.ocr') || 'OCR', render: v => {
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
    setOcrResult(null);
    setUploadedUrl('');
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/files/upload?folder=documents`, {
        method: 'POST',
        body: formData,
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(t('pages.documents.upload.failed') || 'Upload fehlgeschlagen');
      const data = await res.json();
      if (generation !== uploadGeneration.current) return;
      if (!data.file_url) throw new Error('Der Server hat keine Datei zurückgegeben.');
      setUploadedUrl(data.file_url);
      let suggestedType = guessDocType(file.name);

      const ext = file.name.split('.').pop().toLowerCase();
      if (['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif'].includes(ext) && data.file_url) {
        try {
          const ocrRes = await api.post('/documents/ocr-analyze', { file_url: data.file_url });
          if (generation !== uploadGeneration.current) return;
          suggestedType = ocrRes.guessedType || ocrRes.document_type || suggestedType;
          setOcrResult({
            success: Boolean(ocrRes.success ?? ocrRes.analyzed),
            ...ocrRes,
            guessedType: ocrRes.guessedType || ocrRes.document_type || guessDocType(file.name),
            extracted_text: ocrRes.extracted_text || ocrRes.summary || null,
          });
        } catch {
          if (generation !== uploadGeneration.current) return;
          setOcrResult({ success: false, guessedType: guessDocType(file.name), message: t('pages.documents.upload.ocrUnavailable') || 'OCR nicht verfügbar' });
        }
      } else {
        setOcrResult({ success: false, guessedType: guessDocType(file.name), message: t('pages.documents.upload.ocrUnsupported') || 'Dateityp nicht OCR-fähig' });
      }
      if (generation !== uploadGeneration.current) return;
      setCreateInitial({ title: file.name.replace(/\.[^.]+$/, ''), file_url: data.file_url,
        document_type: DOC_TYPES.some(type => type.value === suggestedType) ? suggestedType : 'Sonstiges', tenant_id: tenantId || null });
      setModal('create');
    } catch (err) {
      if (generation === uploadGeneration.current) setError(err.message);
    } finally {
      uploadBusy.current = false;
      if (generation === uploadGeneration.current) setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, [t, canWrite, tenantId, DOC_TYPES]);

  const handleMultiUpload = useCallback(async (files) => {
    if (!canWrite || uploadBusy.current) return;
    uploadBusy.current = true;
    const generation = uploadGeneration.current;
    const fileList = Array.from(files);
    setUploading(true); setError(null); setUploadedUrl(''); setOcrResult(null);
    setUploadQueue(fileList.map(f => ({ name: f.name, status: 'pending' })));
    try {
      for (let i = 0; i < fileList.length; i++) {
        if (generation !== uploadGeneration.current) break;
        setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'uploading' } : q));
        try {
          const file = fileList[i];
          const body = new FormData();
          body.append('file', file);
          body.append('title', file.name.replace(/\.[^.]+$/, ''));
          body.append('document_type', guessDocType(file.name));
          if (tenantId) body.append('tenant_id', tenantId);
          const response = await fetch(`${BASE}/documents/import`, { method: 'POST', body,
            headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` } });
          if (!response.ok) {
            const problem = await response.json().catch(() => null);
            throw new Error(problem?.error?.message || (typeof problem?.detail === 'string' ? problem.detail : `Import fehlgeschlagen (${response.status})`));
          }
          if (generation === uploadGeneration.current) setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'done' } : q));
        } catch (err) {
          if (generation === uploadGeneration.current) setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'failed', error: err.message } : q));
        }
      }
    } finally {
      uploadBusy.current = false;
      if (generation === uploadGeneration.current) { setUploading(false); refreshData(); }
      if (fileRef.current) fileRef.current.value = '';
      store?.invalidateRelated('documents');
    }
  }, [canWrite, tenantId, refreshData, store]);

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
    { key: 'tenant_id', label: 'Mieter / Partei', type: 'select', default: tenantId,
      options: [{ value: '', label: '— Über Vertrag oder ohne Partei —' }, ...tenants.map(person => ({ value: person.id, label: person.full_name }))] },
    { key: 'property_id', label: t('pages.documents.form.property') || 'Immobilie', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noneOption') || '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('pages.documents.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noneOption') || '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'contract_id', label: t('pages.documents.form.contract') || 'Vertrag', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noContract') || '— Kein —' }, ...(tenantId ? (overview?.contracts || []) : contracts).map(c => ({ value: c.id, label: c.contract_number }))] },
    { key: 'description', label: t('pages.documents.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: t('pages.documents.form.tags') || 'Tags', placeholder: t('pages.documents.form.tagsPlaceholder') || 'kommagetrennt' },
    { key: 'file_url', type: 'hidden', required: true, default: uploadedUrl },
  ], [t, DOC_TYPES, tenantId, tenants, properties, units, contracts, overview, uploadedUrl]);

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/documents', data);
    } else {
      await api.put(`/documents/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('documents');
    setUploadedUrl(''); setOcrResult(null); setCreateInitial(null);
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    try {
      await api.del(`/documents/${encodeURIComponent(row.id)}`);
      refreshData();
      if (store) store.invalidateRelated('documents');
    } catch (err) { setError(err.message); }
  };

  return (
    <div className="page documents-page">
      <h1 className="page-title">{t('pages.documents.title') || 'Dokumente'}</h1>
      <div className="toolbar" style={{ flexWrap: 'wrap', marginBottom: '1rem' }}>
        <div className="documents-filter-field documents-party-field">
        <label htmlFor="document-party">Mieter / Partei</label>
        <select id="document-party" value={tenantId} disabled={uploading} onChange={event => {
          setSkip(0); setSearch(''); setDocType(''); setFilter('all'); setUploadedUrl(''); setOcrResult(null); setModal(null);
          setSearchParams(event.target.value ? { tenant_id: event.target.value } : {});
        }}>
          <option value="">Alle Dokumente</option>
          {tenants.map(person => <option key={person.id} value={person.id}>{person.full_name}{person.archived ? ' (archiviert)' : ''}</option>)}
        </select>
        </div>
        {tenantId && party && <button className="btn btn-secondary" onClick={() => party.openParty(tenantId)}>Parteienkarte öffnen</button>}
      </div>
      {tenantId && <p className="text-muted">Dokumente von {overview?.tenant.full_name || 'dieser Partei'} und ihren Mietverträgen. Neue Uploads werden dieser Partei zugeordnet.</p>}
      {searchParams.get('create') === '1' && canWrite && <p role="status">Wählen Sie unten eine oder mehrere Dateien. Bei einer Datei können Sie die Angaben vor dem Speichern prüfen.</p>}
      {error && <div role="alert" className="alert alert-error">{error} <button className="btn btn-sm btn-secondary" onClick={refreshData}>Erneut laden</button></div>}

      {/* Summary cards */}
      {!loading && !error && <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{documentPage?.total ?? enriched.length}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{withFile}</div>
          <div className="kpi-label">Mit Datei{tenantId ? ' auf dieser Seite' : ''}</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{ocrCompleted}</div>
          <div className="kpi-label">OCR erkannt{tenantId ? ' auf dieser Seite' : ''}</div>
        </div>
        {noAssignment > 0 && (
          <div className="kpi">
            <div className="kpi-value" style={{ color: 'var(--warning)' }}>{noAssignment}</div>
            <div className="kpi-label">Ohne Zuordnung</div>
          </div>
        )}
      </div>}

      {/* Filter tabs */}
      {!tenantId && <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'no_assignment', label: 'Ohne Zuordnung' },
          { key: 'ocr_open', label: 'OCR offen' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
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
          {(overview?.document_types || []).map(type => <option key={type} value={type}>{type}</option>)}
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
          <span className="text-muted" style={{ fontSize: '0.8rem' }}>
            {t('pages.documents.upload.supportedFormats') || 'Unterstützt: PDF, PNG, JPG, TIFF, DOC, DOCX, XLS, XLSX — Auto-OCR für Bilddateien und PDFs'}
          </span>
          {uploadedUrl && <span className="text-muted">{t('pages.documents.upload.uploaded') || 'Hochgeladen:'} {uploadedUrl}</span>}
        </div>
        <p className="text-muted">Eine Datei: Angaben prüfen und speichern. Mehrere Dateien: Jede Datei wird als eigenes Dokument mit ihrem Dateinamen importiert.</p>
      </div>}

      {/* Upload queue */}
      {uploadQueue.length > 0 && (
        <div role="status" style={{ marginBottom: '0.5rem' }}>
          {uploadQueue.map((q, i) => (
            <div key={i} className="text-muted" style={{ fontSize: '0.85rem' }}>
              {q.status === 'uploading' ? '⏳' : q.status === 'done' ? '✓' : q.status === 'failed' ? '✗' : '○'} {q.name}
              {q.status === 'done' && ' — Gespeichert'}
              {q.error && <span className="text-red"> — {q.error}. Vor erneutem Import prüfen, ob die Datei bereits gespeichert wurde.</span>}
            </div>
          ))}
        </div>
      )}

      {/* OCR result banner */}
      {ocrResult && (
        <div style={{ marginBottom: '1rem' }}>
          <div className="panel" style={{ padding: '0.75rem 1rem', background: ocrResult.success ? 'var(--success-bg, #f0fdf4)' : 'var(--bg-secondary)' }}>
            <strong>{t('pages.documents.aiAnalysis') || 'KI-Analyse:'}</strong>{' '}
            {ocrResult.success ? (
              <>
                {t('pages.documents.recognizedType') || 'Erkannter Typ:'} <strong>{ocrResult.guessedType}</strong>
                {ocrResult.extracted_text && (
                  <span className="text-muted"> — {ocrResult.extracted_text.slice(0, 150)}...</span>
                )}
              </>
            ) : (
              <>
                {t('pages.documents.recognizedType') || 'Erkannter Typ:'} <strong>{ocrResult.guessedType}</strong>
                <span className="text-muted"> — {ocrResult.message}</span>
              </>
            )}
          </div>
        </div>
      )}

      {loading && <p role="status">Dokumente werden geladen …</p>}
      {!loading && !error && <DataTable
        title={t('pages.documents.title') || 'Dokumente'}
        columns={columns}
        data={filtered}
        serverPaged={Boolean(tenantId)}
        loadExportData={tenantId ? loadPartyExport : undefined}
        onAdd={() => fileRef.current?.click()}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => row.file_url && setViewerFile(row)}
        rowActions={row => row.file_url ? [{ label: 'Dokument ansehen', icon: <span aria-hidden="true">↗</span>, onClick: () => setViewerFile(row) }] : []}
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
          initial={modal === 'create' ? createInitial : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {viewerFile && <FileViewer key={viewerFile.id} fileUrl={viewerFile.file_url} title={viewerFile.title} onClose={() => setViewerFile(null)} />}
    </div>
  );
}
