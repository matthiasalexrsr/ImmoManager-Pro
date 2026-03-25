import { useState, useRef } from 'react';
import { useTranslation } from '../../i18n';
import { useToast } from '../../components/Toast';
import { api } from '../../api';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function BackupSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const [backupStatus, setBackupStatus] = useState(null);
  const [dbInfo, setDbInfo] = useState(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const fileRef = useRef(null);

  const tr = (key, fallback) => {
    const result = t(key);
    return result === key ? fallback : result;
  };

  const loadDbInfo = () => {
    api.get('/admin/database-info').then(setDbInfo).catch(() => setDbInfo({ error: t('toasts.error.generic') }));
  };

  const handleBackup = async () => {
    setBackupStatus(t('toasts.info.syncInProgress'));
    try {
      const result = await api.post('/admin/backup');
      setBackupStatus(`${t('toasts.success.saved')}: ${result?.backup || result?.filename || 'OK'}`);
    } catch {
      setBackupStatus(t('toasts.error.saveFailed'));
    }
  };

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/data/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `immomanager_export_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(`Export fehlgeschlagen: ${err.message}`);
    } finally {
      setExportLoading(false);
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportLoading(true);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/data/import`, {
        method: 'POST',
        body: formData,
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setImportResult(data);
    } catch (err) {
      setImportResult({ errors: { general: [err.message] } });
    } finally {
      setImportLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">{t('pages.settings.dataBackup')}</div>
      <div className="panel-body settings-section">
        <div className="settings-row">
          <label>{t('pages.settings.database')}</label>
          <div className="settings-control">
            <span className="text-muted">{t('pages.settings.dbType')}</span>
            <button className="btn btn-sm btn-secondary" onClick={loadDbInfo} style={{ marginLeft: '0.5rem' }}>
              Info
            </button>
          </div>
        </div>
        {dbInfo && (
          <div className="settings-row">
            <label>{tr('settings.dataBackup.dbDetails', 'DB-Details')}</label>
            <div className="settings-control">
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                {dbInfo.error || JSON.stringify(dbInfo, null, 2).slice(0, 200)}
              </span>
            </div>
          </div>
        )}
        <div className="settings-row">
          <label>Backup</label>
          <div className="settings-control">
            <button className="btn btn-sm btn-primary" onClick={handleBackup}>
              {tr('settings.dataBackup.createBackup', 'Backup erstellen')}
            </button>
            {backupStatus && <span className="text-muted" style={{ marginLeft: '0.5rem', fontSize: '0.8rem' }}>{backupStatus}</span>}
          </div>
        </div>
        <div className="settings-row">
          <label>{t('pages.settings.exportData')}</label>
          <div className="settings-control">
            <button
              className="btn btn-sm btn-secondary"
              onClick={handleExport}
              disabled={exportLoading}
            >
              {exportLoading ? t('pages.settings.exporting') : t('pages.settings.jsonExport')}
            </button>
          </div>
        </div>
        <div className="settings-row">
          <label>{t('pages.settings.importData')}</label>
          <div className="settings-control">
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              onChange={handleImport}
              disabled={importLoading}
              style={{ fontSize: '0.85rem' }}
            />
          </div>
        </div>
        {importResult && (
          <div className="settings-row">
            <label>{t('pages.settings.importResult')}</label>
            <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              {importResult.imported && Object.entries(importResult.imported).map(([k, v]) => (
                <span key={k} className="text-muted">{k}: {v} {t('pages.settings.imported')}</span>
              ))}
              {importResult.errors && Object.keys(importResult.errors).length > 0 && (
                <span style={{ color: 'var(--danger)' }}>
                  {t('pages.settings.errorsIn')} {Object.keys(importResult.errors).join(', ')}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
