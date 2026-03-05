import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api';
import CrudPage from './CrudPage';
import FileViewer from '../components/FileViewer';
import { PlusIcon } from '../components/Icons';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

const COLUMNS = [
  { key: 'title', label: 'Titel', filterType: 'text' },
  { key: 'document_type', label: 'Typ', filterType: 'select' },
  { key: 'document_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'tags', label: 'Tags', filterType: 'text' },
  { key: 'file_url', label: 'Datei', render: v => v ? 'Vorhanden' : '—' },
];

export default function Documents() {
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [viewerFile, setViewerFile] = useState(null);
  const [uploadedUrl, setUploadedUrl] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    Promise.all([
      api.get('/properties').catch(err => { console.warn('[Documents] properties:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Documents] units:', err.message); return []; }),
      api.get('/contracts').catch(err => { console.warn('[Documents] contracts:', err.message); return []; }),
    ]).then(([p, u, c]) => { setProperties(p); setUnits(u); setContracts(c); });
  }, []);

  const uploadFile = useCallback(async (file) => {
    if (!file) return;
    setUploading(true);
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
    } catch (err) {
      console.warn('[Documents] upload failed:', err.message);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer?.files?.[0];
    uploadFile(file);
  }, [uploadFile]);

  const fields = [
    { key: 'title', label: 'Titel', required: true },
    { key: 'document_type', label: 'Dokumententyp', type: 'select', options: [
      { value: 'Mietvertrag', label: 'Mietvertrag' },
      { value: 'Rechnung', label: 'Rechnung' },
      { value: 'Nebenkostenabrechnung', label: 'Nebenkostenabrechnung' },
      { value: 'Protokoll', label: 'Protokoll' },
      { value: 'Versicherung', label: 'Versicherung' },
      { value: 'Sonstiges', label: 'Sonstiges' },
    ]},
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
            style={{ display: 'none' }}
            onChange={e => uploadFile(e.target.files?.[0])}
          />
          <PlusIcon size={24} />
          <span>{uploading ? 'Wird hochgeladen...' : 'Dokument hierher ziehen oder klicken (automatisch speichern)'}</span>
          {uploadedUrl && <span className="text-muted">Hochgeladen: {uploadedUrl}</span>}
        </div>
      </div>
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
