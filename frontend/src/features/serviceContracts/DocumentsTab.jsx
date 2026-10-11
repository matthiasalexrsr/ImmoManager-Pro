import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../api';
import { useTranslation } from '../../i18n';
import FileViewer from '../../components/FileViewer';
import FormModal from '../../components/FormModal';
import { formatDate } from '../../utils/format';

const BASE = import.meta.env.VITE_API_URL || '/api/v1';

// Documents of a contract: linked ones and the scans of its bills; upload goes to the first location's property.
export default function DocumentsTab({ contract, canWrite }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [viewer, setViewer] = useState(null);
  const [linking, setLinking] = useState(null);     // null | documents to choose from
  const [uploading, setUploading] = useState(false);
  const [revision, setRevision] = useState(0);
  const fileRef = useRef(null);
  const base = `/service-contracts/${encodeURIComponent(contract.id)}/documents`;

  useEffect(() => {
    const controller = new AbortController();
    api.get(base, { signal: controller.signal }).then(setRows)
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message); });
    return () => controller.abort();
  }, [base, revision]);

  const reload = () => setRevision(value => value + 1);
  const openLink = () => {
    setLinking([]);
    Promise.all(contract.property_ids.map(id => api.list(`/documents?property_id=${encodeURIComponent(id)}`).catch(() => [])))
      .then(lists => setLinking(lists.flat()));
  };
  const linkFields = useMemo(() => {
    const present = new Set((rows || []).map(row => row.id));
    return [{ key: 'document_id', label: t('serviceContracts.fields.document'), type: 'select', required: true,
      options: (linking || []).filter(d => !present.has(d.id)).map(d => ({ value: d.id,
        label: `${d.title}${d.document_date ? ` · ${formatDate(d.document_date)}` : ''}` })) }];
  }, [t, linking, rows]);

  const upload = async file => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(`${BASE}/files/upload?folder=documents`, {
        method: 'POST', body: form, credentials: 'include',
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      });
      if (!response.ok) throw new Error(t('serviceContracts.uploadFailed'));
      const uploaded = await response.json();
      const document = await api.post('/documents', {
        title: file.name.replace(/\.[^.]+$/, ''), document_type: 'service_contract', file_url: uploaded.file_url,
        property_id: contract.property_ids[0] || null, document_date: new Date().toISOString().slice(0, 10),
      });
      await api.post(base, { document_id: document.id });
      reload();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const unlink = async row => {
    setError(null);
    try { await api.del(`${base}/${encodeURIComponent(row.link_id)}`); reload(); } catch (failure) { setError(failure.message); }
  };

  return (
    <div className="panel">
      <div className="panel-header sc-panel-header">
        <span>{t('serviceContracts.tabs.documents')}</span>
        {canWrite && <span className="sc-row-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={openLink}>{t('serviceContracts.linkDocument')}</button>
          <label className="btn btn-sm btn-primary sc-upload">
            {uploading ? t('serviceContracts.uploading') : t('serviceContracts.uploadDocument')}
            <input ref={fileRef} type="file" className="sr-only" disabled={uploading}
              onChange={e => upload(e.target.files?.[0])} />
          </label>
        </span>}
      </div>
      <div className="panel-body">
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        {rows === null ? <p role="status">{t('serviceContracts.loading')}</p> : rows.length === 0
          ? <p className="empty-text">{t('serviceContracts.noDocuments')}</p> : (
            <ul className="activity-list sc-documents">
              {rows.map(row => (
                <li key={`${row.source}-${row.id}`}>
                  <button type="button" className="dossier-document-link" onClick={() => setViewer(row)}
                    aria-label={`${t('serviceContracts.openDocument')}: ${row.title}`}>{row.title}</button>
                  <span className="text-muted">{row.source === 'invoice' ? t('serviceContracts.fromBill') : formatDate(row.document_date)}</span>
                  {canWrite && row.link_id && <button type="button" className="btn btn-sm btn-secondary"
                    aria-label={`${t('serviceContracts.unlink')}: ${row.title}`} onClick={() => unlink(row)}>{t('serviceContracts.unlink')}</button>}
                </li>
              ))}
            </ul>
          )}
      </div>
      {linking && <FormModal title={t('serviceContracts.linkDocument')} fields={linkFields}
        onSave={async values => { await api.post(base, { document_id: values.document_id }); reload(); }}
        onClose={() => setLinking(null)} />}
      {viewer && <FileViewer key={viewer.id} fileUrl={viewer.file_url} title={viewer.title} onClose={() => setViewer(null)} />}
    </div>
  );
}
