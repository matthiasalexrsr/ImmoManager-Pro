import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';
import FileViewer from '../components/FileViewer';
import { PlusIcon } from '../components/Icons';
import { useTranslation } from '../i18n';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');


function guessDocType(filename) {
  const lower = (filename || '').toLowerCase();
  if (/mietvertrag|lease|vertrag/.test(lower)) return 'Mietvertrag';
  if (/rechnung|invoice|faktura/.test(lower)) return 'Rechnung';
  if (/nebenkosten|betriebskosten/.test(lower)) return 'Nebenkostenabrechnung';
  if (/protokoll|übergabe/.test(lower)) return 'Protokoll';
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

  const DOC_TYPES = [
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
  ];

  const COLUMNS = [
    { key: 'title', label: t('pages.documents.columns.title') || 'Titel', filterType: 'text' },
    { key: 'document_type', label: t('pages.documents.columns.type') || 'Typ', filterType: 'select' },
    { key: 'document_date', label: t('pages.documents.columns.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'tags', label: t('pages.documents.columns.tags') || 'Tags', filterType: 'text' },
    { key: 'file_url', label: t('pages.documents.columns.file') || 'Datei', render: v => v ? (t('pages.documents.columns.filePresent') || 'Vorhanden') : '—' },
    { key: 'ocr_status', label: t('pages.documents.columns.ocr') || 'OCR', render: v => {
      if (v === 'completed') return t('pages.documents.ocr.completed') || '✓ Erkannt';
      if (v === 'processing') return t('pages.documents.ocr.processing') || '⏳ Läuft...';
      if (v === 'failed') return t('pages.documents.ocr.failed') || '✗ Fehler';
      return '—';
    }},
  ];
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [viewerFile, setViewerFile] = useState(null);
  const [uploadedUrl, setUploadedUrl] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [ocrResult, setOcrResult] = useState(null);
  const [stats, setStats] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => {
    api.get('/documents').catch(() => []).then(docs => {
      const docArr = Array.isArray(docs) ? docs : [];
      setStats({
        total: docArr.length,
        withFile: docArr.filter(d => d.file_url).length,
        byType: DOC_TYPES.map(t => ({
          label: t.label,
          count: docArr.filter(d => d.document_type === t.value).length,
        })).filter(x => x.count > 0),
      });
    });
  }, []);

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

      // Try OCR analysis for supported file types
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
  }, []);

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
    { key: 'file_url', label: t('pages.documents.form.fileUrl') || 'Datei-URL', required: true, placeholder: '/uploads/documents/...', default: uploadedUrl },
  ];

  return (
    <div>
      {/* Stats bar */}
      {stats && (
        <div style={{ padding: '1rem 1.5rem 0', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats.total}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>{t('pages.documents.totalDocs') || 'Dokumente gesamt'}</div>
          </div>
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats.withFile}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>{t('pages.documents.withFile') || 'Mit Datei'}</div>
          </div>
          {stats.byType.slice(0, 5).map(item => (
            <div key={item.label} className="panel" style={{ padding: '0.75rem 1rem', minWidth: '100px', textAlign: 'center' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{item.count}</div>
              <div className="text-muted" style={{ fontSize: '0.75rem' }}>{item.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Upload zone */}
      <div className="photo-drop-zone-container" style={{ padding: '1rem 1.5rem 0' }}>
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
        <div style={{ padding: '0.5rem 1.5rem' }}>
          {uploadQueue.map((q, i) => (
            <div key={i} className="text-muted" style={{ fontSize: '0.85rem' }}>
              {q.status === 'uploading' ? '⏳' : q.status === 'done' ? '✓' : '○'} {q.name}
            </div>
          ))}
        </div>
      )}

      {/* OCR result banner */}
      {ocrResult && (
        <div style={{ padding: '0.5rem 1.5rem' }}>
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

      <CrudPage
        title={t('pages.documents.title') || 'Dokumente'}
        endpoint="/documents"
        columns={COLUMNS}
        formFields={fields}
        onRowClick={row => row.file_url && setViewerFile(row.file_url)}
      />
      {viewerFile && <FileViewer key={viewerFile} fileUrl={viewerFile} onClose={() => setViewerFile(null)} />}
    </div>
  );
}
