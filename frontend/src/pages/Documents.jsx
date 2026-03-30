import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { api } from '../api';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import FileViewer from '../components/FileViewer';
import { PlusIcon } from '../components/Icons';
import { useConfirm } from '../components/ConfirmDialog';
import { useTranslation } from '../i18n';

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
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
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
  const fileRef = useRef(null);

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

  const refreshData = () => {
    setLoading(true);
    api.get('/documents').catch(() => [])
      .then(data => setDocuments(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/documents').catch(() => [])
      .then(data => { if (!cancelled) setDocuments(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const contractMap = Object.fromEntries(contracts.map(c => [c.id, c.contract_number]));

  const enriched = documents.map(doc => ({
    ...doc,
    property_name: propMap[doc.property_id] || '—',
    unit_label: unitMap[doc.unit_id] || '—',
    contract_label: contractMap[doc.contract_id] || '—',
    has_file: !!doc.file_url,
  }));

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'no_assignment') return enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id);
    if (filter === 'ocr_open') return enriched.filter(d => d.ocr_status === 'processing' || (!d.ocr_status && d.file_url));
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const withFile = enriched.filter(d => d.file_url).length;
  const noAssignment = enriched.filter(d => !d.property_id && !d.unit_id && !d.contract_id).length;
  const ocrCompleted = enriched.filter(d => d.ocr_status === 'completed').length;

  const columns = [
    { key: 'title', label: t('pages.documents.columns.title') || 'Titel', filterType: 'text' },
    { key: 'document_type', label: t('pages.documents.columns.type') || 'Typ', filterType: 'select' },
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
    if (!file) return;
    setUploading(true);
    setOcrResult(null);
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
      if (data.file_url) setUploadedUrl(data.file_url);

      const ext = file.name.split('.').pop().toLowerCase();
      if (['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif'].includes(ext) && data.file_url) {
        try {
          const ocrRes = await api.post('/documents/ocr-analyze', { file_url: data.file_url });
          setOcrResult({ success: true, ...ocrRes, guessedType: guessDocType(file.name) });
        } catch {
          setOcrResult({ success: false, guessedType: guessDocType(file.name), message: t('pages.documents.upload.ocrUnavailable') || 'OCR nicht verfügbar' });
        }
      } else {
        setOcrResult({ success: false, guessedType: guessDocType(file.name), message: t('pages.documents.upload.ocrUnsupported') || 'Dateityp nicht OCR-fähig' });
      }
    } catch (err) {
      setOcrResult({ success: false, guessedType: 'Sonstiges', message: `${t('pages.documents.upload.failed') || 'Upload fehlgeschlagen'}: ${err.message}` });
    } finally {
      setUploading(false);
    }
  }, [t]);

  const handleMultiUpload = useCallback(async (files) => {
    const fileList = Array.from(files);
    setUploadQueue(fileList.map(f => ({ name: f.name, status: 'pending' })));
    for (let i = 0; i < fileList.length; i++) {
      setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'uploading' } : q));
      await uploadFile(fileList[i]);
      setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'done' } : q));
    }
    setTimeout(() => setUploadQueue([]), 3000);
  }, [uploadFile]);

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

  const fields = [
    { key: 'title', label: t('pages.documents.form.title') || 'Titel', required: true },
    { key: 'document_type', label: t('pages.documents.form.docType') || 'Dokumententyp', type: 'select', options: DOC_TYPES },
    { key: 'document_date', label: t('pages.documents.form.date') || 'Datum', type: 'date' },
    { key: 'property_id', label: t('pages.documents.form.property') || 'Immobilie', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noneOption') || '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('pages.documents.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noneOption') || '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'contract_id', label: t('pages.documents.form.contract') || 'Vertrag', type: 'select',
      options: [{ value: '', label: t('pages.documents.form.noContract') || '— Kein —' }, ...contracts.map(c => ({ value: c.id, label: c.contract_number }))] },
    { key: 'description', label: t('pages.documents.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: t('pages.documents.form.tags') || 'Tags', placeholder: t('pages.documents.form.tagsPlaceholder') || 'kommagetrennt' },
    { key: 'file_url', type: 'hidden', required: true, default: uploadedUrl },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/documents', data);
    } else {
      await api.put(`/documents/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('documents');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/documents/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('documents');
  };

  if (loading) return <div className="page-loading">Lade Dokumente...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.documents.title') || 'Dokumente'}</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{enriched.length}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{withFile}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Mit Datei</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{ocrCompleted}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>OCR erkannt</div>
        </div>
        {noAssignment > 0 && (
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{noAssignment}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ohne Zuordnung</div>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'no_assignment', label: 'Ohne Zuordnung' },
          { key: 'ocr_open', label: 'OCR offen' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Upload zone */}
      <div style={{ marginBottom: '1rem' }}>
        <div
          className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            multiple
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
      </div>

      {/* Upload queue */}
      {uploadQueue.length > 0 && (
        <div style={{ marginBottom: '0.5rem' }}>
          {uploadQueue.map((q, i) => (
            <div key={i} className="text-muted" style={{ fontSize: '0.85rem' }}>
              {q.status === 'uploading' ? '⏳' : q.status === 'done' ? '✓' : '○'} {q.name}
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

      <DataTable
        title={t('pages.documents.title') || 'Dokumente'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => row.file_url && setViewerFile(row.file_url)}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Dokument erstellen' : 'Dokument bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {viewerFile && <FileViewer key={viewerFile} fileUrl={viewerFile} onClose={() => setViewerFile(null)} />}
    </div>
  );
}
