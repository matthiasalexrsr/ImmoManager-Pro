import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useTranslation } from '../../i18n';
import FileViewer from '../../components/FileViewer';
import FormModal from '../../components/FormModal';
import { formatDate } from '../../utils/format';
import useLookupChoices from '../../hooks/useLookupChoices';


// Documents of a contract: linked ones and the scans of its bills; upload goes to the first location's property.
export default function DocumentsTab({ contract, canWrite }) {
  return <ContractDocuments key={contract.id} contract={contract} canWrite={canWrite} />;
}

function ContractDocuments({ contract, canWrite }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [viewer, setViewer] = useState(null);
  const [linking, setLinking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [revision, setRevision] = useState(0);
  const fileRef = useRef(null);
  const currentContract = useRef(contract.id);
  currentContract.current = contract.id;
  useEffect(() => { currentContract.current = contract.id; return () => { currentContract.current = null; }; }, [contract.id]);
  const base = `/service-contracts/${encodeURIComponent(contract.id)}/documents`;
  const sourcePaths = Object.fromEntries([...new Set(contract.property_ids || [])].map(id => [id, `/documents?property_id=${encodeURIComponent(id)}`]));
  const choices = useLookupChoices(sourcePaths, linking, contract.id);
  const recordsReady = rows !== null && !loadError;

  useEffect(() => {
    const controller = new AbortController();
    api.get(base, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value)) throw new Error('Die Dokumentliste konnte nicht vollständig gelesen werden.');
      setRows(value); setLoadError(null);
    }).catch(failure => { if (!controller.signal.aborted) setLoadError(failure.message); });
    return () => controller.abort();
  }, [base, revision]);

  const reload = () => setRevision(value => value + 1);
  const linkFields = useMemo(() => {
    const present = new Set((rows || []).map(row => row.id));
    return [{ key: 'document_id', label: t('serviceContracts.fields.document'), type: 'select', required: true,
      options: [...new Map(Object.values(choices.data).flat().map(document => [document.id, document])).values()]
        .filter(d => !present.has(d.id)).map(d => ({ value: d.id,
        label: `${d.title}${d.document_date ? ` · ${formatDate(d.document_date)}` : ''}` })) }];
  }, [t, choices.data, rows]);

  const upload = async file => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const current = api.captureSession();
      const form = new FormData();
      form.append('file', file);
      const uploaded = await api.upload('/files/upload?folder=documents', form);
      current();
      if (currentContract.current !== contract.id) return;
      if (!uploaded?.file_url) throw new Error(t('serviceContracts.uploadFailed'));
      const document = await api.post('/documents', {
        title: file.name.replace(/\.[^.]+$/, ''), document_type: 'service_contract', file_url: uploaded.file_url,
        property_id: contract.property_ids[0] || null, document_date: new Date().toISOString().slice(0, 10),
      });
      current();
      if (currentContract.current !== contract.id) return;
      await api.post(base, { document_id: document.id });
      current();
      if (currentContract.current !== contract.id) return;
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
          <button type="button" className="btn btn-sm btn-secondary" disabled={!recordsReady || linking} onClick={() => setLinking(true)}>{t('serviceContracts.linkDocument')}</button>
          <label className="btn btn-sm btn-primary sc-upload">
            {uploading ? t('serviceContracts.uploading') : t('serviceContracts.uploadDocument')}
            <input ref={fileRef} type="file" className="sr-only" disabled={uploading || !recordsReady}
              onChange={e => upload(e.target.files?.[0])} />
          </label>
        </span>}
      </div>
      <div className="panel-body">
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        {loadError && <div role="alert" className="alert alert-error">{loadError}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={reload}>{t('serviceContracts.retry')}</button></div>}
        {linking && !choices.ready && <div role={choices.error ? 'alert' : 'status'} className={choices.error ? 'alert alert-error' : ''}>
          {choices.error || t('serviceContracts.loading')}{' '}
          {choices.error && <button type="button" className="btn btn-secondary btn-sm" onClick={choices.reload}>Auswahl erneut laden</button>}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setLinking(false)}>{t('ui.buttons.cancel')}</button>
        </div>}
        {rows === null ? !loadError && <p role="status">{t('serviceContracts.loading')}</p> : rows.length === 0
          ? <p className="empty-text">{t('serviceContracts.noDocuments')}</p> : (
            <ul className="activity-list sc-documents">
              {rows.map(row => (
                <li key={`${row.source}-${row.id}`}>
                  <button type="button" className="dossier-document-link" onClick={() => setViewer(row)}
                    aria-label={`${t('serviceContracts.openDocument')}: ${row.title}`}>{row.title}</button>
                  <span className="text-muted">{row.source === 'invoice' ? t('serviceContracts.fromBill') : formatDate(row.document_date)}</span>
                  <Link className="btn btn-sm btn-secondary" to={`/documents?focus_id=${encodeURIComponent(row.id)}`}
                    aria-label={`Dokumentenakte: ${row.title}`}>Dokumentenakte</Link>
                  {canWrite && row.link_id && <button type="button" className="btn btn-sm btn-secondary"
                    disabled={!recordsReady} aria-label={`${t('serviceContracts.unlink')}: ${row.title}`} onClick={() => unlink(row)}>{t('serviceContracts.unlink')}</button>}
                </li>
              ))}
            </ul>
          )}
      </div>
      {linking && choices.ready && <FormModal title={t('serviceContracts.linkDocument')} fields={linkFields}
        onSave={async values => { await api.post(base, { document_id: values.document_id }); reload(); }}
        onClose={() => setLinking(false)} />}
      {viewer && <FileViewer key={viewer.id} fileUrl={viewer.file_url} title={viewer.title} onClose={() => setViewer(null)} />}
    </div>
  );
}
