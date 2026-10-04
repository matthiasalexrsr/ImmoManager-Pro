import useWriteAccess from '../hooks/useWriteAccess';
import { revisionOptions } from '../editRevision';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { principalKey, errorMessage } from '../features/unitInventory/read';
import DocumentInventoryList from '../features/documentInventory/DocumentInventoryList';
import { useDocumentInventory } from '../features/documentInventory/useDocumentInventory';
import DocumentInventoryForm from '../features/documentInventory/DocumentInventoryForm';
import { api } from '../api';
import { useDataStore } from '../contexts/DataStoreContext';
import FileViewer from '../components/FileViewer';
import DocumentVersionHistory from '../components/DocumentVersionHistory';
import { PlusIcon } from '../components/Icons';
import { useConfirm } from '../components/ConfirmDialog';
import { useTranslation } from '../i18n';
import { ocrFailure } from '../utils/ocrFailure';
import './Documents.css';

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

function DocumentsPage({ principal }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const listing = useDocumentInventory(principal);
  const [readError, setReadError] = useState(null);
  const editRequest = useRef(null);
  const mounted = useRef(true);
  const uploadRequest = useRef(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; editRequest.current?.abort(); uploadRequest.current?.abort(); }; }, []);
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed: grantAllowed, requireWrite } = useWriteAccess('/documents', () => { editRequest.current?.abort(); uploadRequest.current?.abort(); setModal(null); setUploadedUrl(''); setOcrResult(null); setUploadQueue([]); setDragActive(false); if (fileRef.current) fileRef.current.value = ''; });
  const isAllowed = useCallback(() => mounted.current && grantAllowed(), [grantAllowed]);
  const [viewerFile, setViewerFile] = useState(null);
  const [historyDocument, setHistoryDocument] = useState(null);
  const [uploadedUrl, setUploadedUrl] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [ocrResult, setOcrResult] = useState(null);
  const [ocrBusy, setOcrBusy] = useState(false);
  const ocrInFlight = useRef(false);
  const uploadInFlight = useRef(false);
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
    { value: 'housing_confirmation', label: 'Wohnungsgeberbestätigung' },
    { value: 'Sonstiges', label: t('pages.documents.docTypes.sonstiges') || 'Sonstiges' },
  ], [t]);

  const refreshData = listing.refresh;
  const editDocument = async row => {
    editRequest.current?.abort();
    const controller = new AbortController(); editRequest.current = controller;
    setReadError(null);
    try {
      const current = await api.get(`/documents/${encodeURIComponent(row.id)}`, { signal: controller.signal });
      if (!current || current.id !== row.id) throw new Error('Die Antwort gehört nicht zum ausgewählten Dokument.');
      if (!controller.signal.aborted && isAllowed()) setModal(current);
    } catch (error) { if (!controller.signal.aborted) setReadError(error); }
  };

  const analyzeUploaded = useCallback(async (fileUrl, filename) => {
    if (!isAllowed() || ocrInFlight.current) return;
    ocrInFlight.current = true;
    setOcrBusy(true);
    try {
      const result = await api.post('/documents/ocr-analyze', { file_url: fileUrl });
      if (!isAllowed()) return;
      setOcrResult({ ...result, success: Boolean(result.success ?? result.analyzed),
        guessedType: result.guessedType || result.document_type || guessDocType(filename),
        extracted_text: result.extracted_text || result.summary || null,
        originalSaved: true, sourceUrl: fileUrl, sourceName: filename });
    } catch (error) {
      if (!isAllowed()) return;
      setOcrResult({ ...ocrFailure(error, t), guessedType: guessDocType(filename),
        originalSaved: true, sourceUrl: fileUrl, sourceName: filename });
    } finally {
      ocrInFlight.current = false;
      setOcrBusy(false);
    }
  }, [isAllowed, t]);

  const uploadFile = useCallback(async (file) => {
    if (!file || !isAllowed() || uploadInFlight.current || ocrInFlight.current) return;
    uploadInFlight.current = true;
    setUploading(true);
    setOcrResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const controller = new AbortController(); uploadRequest.current = controller;
      const res = await fetch(`${BASE}/files/upload?folder=documents`, {
        method: 'POST',
        body: formData,
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(t('pages.documents.upload.failed') || 'Upload fehlgeschlagen');
      const data = await res.json();
      if (!isAllowed()) return;
      if (data.file_url) setUploadedUrl(data.file_url);

      const ext = file.name.split('.').pop().toLowerCase();
      if (data.ocr_error && data.file_url) {
        setOcrResult({ ...ocrFailure(data.ocr_error, t), guessedType: guessDocType(file.name),
          originalSaved: true, sourceUrl: data.file_url, sourceName: file.name });
      } else if (['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp'].includes(ext) && data.file_url) {
        await analyzeUploaded(data.file_url, file.name);
      } else {
        setOcrResult({ success: false, guessedType: guessDocType(file.name), message: t('pages.documents.upload.ocrUnsupported') || 'Dateityp nicht OCR-fähig' });
      }
    } catch (err) {
      if (!isAllowed()) return;
      setOcrResult({ success: false, guessedType: 'Sonstiges', message: `${t('pages.documents.upload.failed') || 'Upload fehlgeschlagen'}: ${err.message}` });
    } finally {
      uploadInFlight.current = false;
      setUploading(false);
    }
  }, [t, isAllowed, analyzeUploaded]);

  const handleMultiUpload = useCallback(async (files) => {
    if (!isAllowed()) return;
    const fileList = Array.from(files);
    setUploadQueue(fileList.map(f => ({ name: f.name, status: 'pending' })));
    for (let i = 0; i < fileList.length; i++) {
      if (!isAllowed()) break;
      setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'uploading' } : q));
      await uploadFile(fileList[i]);
      setUploadQueue(prev => prev.map((q, j) => j === i ? { ...q, status: 'done' } : q));
    }
    setTimeout(() => setUploadQueue([]), 3000);
  }, [uploadFile, isAllowed]);

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
    { key: 'document_type', label: t('pages.documents.form.docType') || 'Dokumententyp', type: 'select', options: modal?.document_type && !DOC_TYPES.some(option => option.value === modal.document_type) ? [...DOC_TYPES, { value: modal.document_type, label: modal.document_type }] : DOC_TYPES },
    { key: 'document_date', label: t('pages.documents.form.date') || 'Datum', type: 'date' },
    { key: 'description', label: t('pages.documents.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'tags', label: t('pages.documents.form.tags') || 'Tags', placeholder: t('pages.documents.form.tagsPlaceholder') || 'kommagetrennt' },
    { key: 'file_url', type: 'hidden', required: true, default: uploadedUrl },
  ];

  const handleSave = async (data) => {
    requireWrite();
    if (!mounted.current) throw new Error('Die Anmeldung wurde geändert.');
    if (modal === 'create') {
      await api.post('/documents', data);
    } else {
      await api.put(`/documents/${modal.id}`, data, { ...revisionOptions(modal), ...revisionOptions(data) });
    }
    if (isAllowed()) { refreshData(); store?.invalidateRelated('documents'); }
  };

  const handleDelete = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    if (!isAllowed()) return;
    try {
      await api.del(`/documents/${row.id}`, revisionOptions(row));
      refreshData();
      if (store) store.invalidateRelated('documents');
    } catch (error) { setReadError(error); }
  };

  return (
    <div className="page documents-page unit-inventory">
      <h1 className="page-title">{t('pages.documents.title') || 'Dokumente'}</h1>

      {readError && <div className="panel inventory-error" role="alert">{errorMessage(readError)}</div>}
      <DocumentInventoryList listing={listing} principal={principal} types={DOC_TYPES}
        onAdd={canWrite ? () => setModal('create') : undefined}
        onEdit={canWrite ? editDocument : undefined} onDelete={canWrite ? handleDelete : undefined}
        onView={row => setViewerFile(row.file_url)} onHistory={setHistoryDocument} />

      {/* Upload zone */}
      {canWrite && <div style={{ marginBottom: '1rem' }}>
        <div
          className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          role="button" tabIndex={0} aria-disabled={uploading || ocrBusy}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileRef.current?.click(); } }}
        >
          <input
            ref={fileRef}
            type="file"
            multiple
            disabled={uploading || ocrBusy}
            style={{ display: 'none' }}
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp,.doc,.docx,.xls,.xlsx"
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
      </div>}

      {/* Upload queue */}
      {canWrite && uploadQueue.length > 0 && (
        <div style={{ marginBottom: '0.5rem' }}>
          {uploadQueue.map((q, i) => (
            <div key={i} className="text-muted" style={{ fontSize: '0.85rem' }}>
              {q.status === 'uploading' ? '⏳' : q.status === 'done' ? '✓' : '○'} {q.name}
            </div>
          ))}
        </div>
      )}

      {/* OCR result banner */}
      {canWrite && ocrResult && (
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
                {ocrResult.code && <div style={{ overflowWrap: 'anywhere' }}><small>{ocrResult.httpStatus && `HTTP ${ocrResult.httpStatus} · `}{ocrResult.code}</small></div>}
                {ocrResult.correction && <p>{ocrResult.correction}</p>}
              </>
            )}
          </div>
          {ocrResult.originalSaved && <p role="status">{t('documentsOCR.originalSaved')}</p>}
          {!ocrResult.success && ocrResult.sourceUrl && <button type="button" className="btn btn-secondary"
            disabled={ocrBusy || uploading} onClick={() => analyzeUploaded(ocrResult.sourceUrl, ocrResult.sourceName)}>
            {ocrBusy ? t('documentsOCR.analyzing') : t('documentsOCR.retry')}
          </button>}
        </div>
      )}

      {modal && canWrite && (
        <DocumentInventoryForm
          key={modal.id || 'create'} principal={principal}
          uploadedUrl={uploadedUrl} onFileChange={uploadFile} uploading={uploading || ocrBusy}
          title={modal === 'create' ? 'Dokument erstellen' : 'Dokument bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {viewerFile && <FileViewer key={viewerFile} fileUrl={viewerFile} onClose={() => setViewerFile(null)} />}
      {historyDocument && <DocumentVersionHistory key={historyDocument.id} document={historyDocument}
        onClose={() => setHistoryDocument(null)} />}
    </div>
  );
}

export default function Documents() {
  const principal = principalKey(useAuth()?.user);
  return <DocumentsPage key={principal} principal={principal} />;
}
