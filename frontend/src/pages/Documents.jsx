import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';
import FileViewer from '../components/FileViewer';
import { PlusIcon } from '../components/Icons';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

const DOC_TYPES = [
  { value: 'Mietvertrag', label: 'Mietvertrag' },
  { value: 'Rechnung', label: 'Rechnung' },
  { value: 'Nebenkostenabrechnung', label: 'Nebenkostenabrechnung' },
  { value: 'Protokoll', label: 'Protokoll' },
  { value: 'Versicherung', label: 'Versicherung' },
  { value: 'Grundbuchauszug', label: 'Grundbuchauszug' },
  { value: 'Energieausweis', label: 'Energieausweis' },
  { value: 'Betriebskostenabrechnung', label: 'Betriebskostenabrechnung' },
  { value: 'Mahnung', label: 'Mahnung' },
  { value: 'Kündigung', label: 'Kündigung' },
  { value: 'Übergabeprotokoll', label: 'Übergabeprotokoll' },
  { value: 'Handwerkerrechnung', label: 'Handwerkerrechnung' },
  { value: 'Steuerbescheid', label: 'Steuerbescheid' },
  { value: 'Sonstiges', label: 'Sonstiges' },
];

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

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'document_type', label: 'Typ', filterType: 'select' },
  { key: 'document_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'tags', label: 'Tags', filterType: 'text' },
  { key: 'file_url', label: 'Datei', render: v => v ? 'Vorhanden' : '—' },
  { key: 'ocr_status', label: 'OCR', render: v => {
    if (v === 'completed') return '✓ Erkannt';
    if (v === 'processing') return '⏳ Läuft...';
    if (v === 'failed') return '✗ Fehler';
    return '—';
  }},
];

export default function Documents() {
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
      if (!res.ok) throw new Error('Upload fehlgeschlagen');
      const data = await res.json();
      if (data.file_url) setUploadedUrl(data.file_url);

      // Try OCR analysis for supported file types
      const ext = file.name.split('.').pop().toLowerCase();
      if (['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif'].includes(ext) && data.file_url) {
        try {
          const ocrRes = await api.post('/documents/ocr-analyze', { file_url: data.file_url });
          setOcrResult({ success: true, ...ocrRes, guessedType: guessDocType(file.name) });
        } catch {
          setOcrResult({ success: false, guessedType: guessDocType(file.name), message: 'OCR nicht verfügbar' });
        }
      } else {
        setOcrResult({ success: false, guessedType: guessDocType(file.name), message: 'Dateityp nicht OCR-fähig' });
      }
    } catch (err) {
      console.warn('[Documents] upload failed:', err.message);
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
    { key: 'title', label: 'Titel', required: true },
    { key: 'document_type', label: 'Dokumententyp', type: 'select', options: DOC_TYPES },
    { key: 'document_date', label: 'Datum', type: 'date' },
    { key: 'property_id', label: 'Immobilie', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: [{ value: '', label: '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'contract_id', label: 'Vertrag', type: 'select',
      options: [{ value: '', label: '— Kein —' }, ...contracts.map(c => ({ value: c.id, label: c.contract_number }))] },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: 'Tags', placeholder: 'kommagetrennt' },
    { key: 'file_url', label: 'Datei-URL', required: true, placeholder: '/uploads/documents/...', default: uploadedUrl },
  ];

  return (
    <div>
      {/* Stats bar */}
      {stats && (
        <div style={{ padding: '1rem 1.5rem 0', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats.total}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>Dokumente gesamt</div>
          </div>
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '120px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats.withFile}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>Mit Datei</div>
          </div>
          {stats.byType.slice(0, 5).map(t => (
            <div key={t.label} className="panel" style={{ padding: '0.75rem 1rem', minWidth: '100px', textAlign: 'center' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{t.count}</div>
              <div className="text-muted" style={{ fontSize: '0.75rem' }}>{t.label}</div>
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
          <span>{uploading ? 'Wird hochgeladen...' : 'Dokumente hierher ziehen oder klicken (mehrere Dateien möglich)'}</span>
          <span className="text-muted" style={{ fontSize: '0.8rem' }}>
            Unterstützt: PDF, PNG, JPG, TIFF, DOC, DOCX, XLS, XLSX — Auto-OCR für Bilddateien und PDFs
          </span>
          {uploadedUrl && <span className="text-muted">Hochgeladen: {uploadedUrl}</span>}
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
            <strong>KI-Analyse:</strong>{' '}
            {ocrResult.success ? (
              <>
                Erkannter Typ: <strong>{ocrResult.guessedType}</strong>
                {ocrResult.extracted_text && (
                  <span className="text-muted"> — {ocrResult.extracted_text.slice(0, 150)}...</span>
                )}
              </>
            ) : (
              <>
                Erkannter Typ: <strong>{ocrResult.guessedType}</strong>
                <span className="text-muted"> — {ocrResult.message}</span>
              </>
            )}
          </div>
        </div>
      )}

      <CrudPage
        title="Dokumente"
        endpoint="/documents"
        columns={COLUMNS}
        formFields={fields}
        onRowClick={row => row.file_url && setViewerFile(row.file_url)}
      />
      {viewerFile && <FileViewer key={viewerFile} fileUrl={viewerFile} onClose={() => setViewerFile(null)} />}
    </div>
  );
}
