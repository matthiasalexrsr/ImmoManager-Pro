import { useState, useRef } from 'react';
import { useTranslation } from '../../i18n';
import { useToast } from '../../components/Toast';
import { useAuth } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { api } from '../../api';

const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exportCollections = ['portfolios', 'properties', 'units', 'tenants', 'contracts', 'bookings', 'receivables', 'rent_charges', 'payments'];

export default function BackupSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const cache = useDataStore();
  const toast = useToast();
  const [backupResult, setBackupResult] = useState(null);
  const [dbInfo, setDbInfo] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const fileRef = useRef(null);
  const inFlight = useRef(false);
  const tr = (key, fallback) => {
    const value = t(`settings.dataBackup.${key}`);
    return value === `settings.dataBackup.${key}` ? fallback : value;
  };
  const begin = (operation, mutation = false) => {
    if (inFlight.current || (mutation && auth?.isReadonly)) return false;
    inFlight.current = true;
    setBusy(operation);
    setError(null);
    return true;
  };
  const finish = () => { inFlight.current = false; setBusy(null); };
  const fail = (label, cause) => {
    const status = Number.isInteger(cause?.statusCode) ? ` (HTTP ${cause.statusCode})` : '';
    const message = `${label}${status}: ${cause?.message || t('toasts.error.generic')}`;
    setError({ message, details: cause?.details });
    toast.error(message);
  };

  const loadDbInfo = async () => {
    if (!begin('info')) return;
    try { setDbInfo(await api.get('/admin/database-info')); }
    catch (cause) { fail(tr('infoFailed', 'Datenbankinfo fehlgeschlagen'), cause); }
    finally { finish(); }
  };

  const handleBackup = async () => {
    if (!begin('backup', true)) return;
    setBackupResult(null);
    try {
      const result = await api.post('/admin/backup');
      if (!isObject(result) || result.scope !== 'business-data-only'
        || typeof result.backup !== 'string' || !result.backup.trim() || !result.backup.endsWith('.json')
        || /[\\/]/.test(result.backup) || [...result.backup].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
        || !Number.isSafeInteger(result.size_bytes) || result.size_bytes <= 0) {
        throw new Error(tr('invalidBackup', 'Die Serverantwort bestätigt keine gültige Teil-Geschäftsdatensicherung.'));
      }
      setBackupResult(result);
    } catch (cause) { fail(tr('backupFailed', 'Sicherung fehlgeschlagen'), cause); }
    finally { finish(); }
  };

  const handleExport = async () => {
    if (!begin('export')) return;
    try {
      const blob = await api.getBlob('/data/export');
      if (!(blob instanceof Blob) || blob.type.split(';')[0].trim() !== 'application/json') {
        throw new Error(tr('invalidExport', 'Die Antwort ist kein gültiger JSON-Geschäftsdatenexport.'));
      }
      let data;
      try { data = JSON.parse(await blob.text()); }
      catch { throw new Error(tr('invalidExport', 'Die Antwort ist kein gültiger JSON-Geschäftsdatenexport.')); }
      if (!isObject(data) || typeof data.version !== 'string' || !data.version.trim()
        || typeof data.exported_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(data.exported_at) || !Number.isFinite(Date.parse(data.exported_at))
        || !exportCollections.every(key => Array.isArray(data[key]))
        || !Object.entries(data).every(([key, value]) => ['version', 'exported_at'].includes(key)
          || (Array.isArray(value) && value.every(isObject)))) {
        throw new Error(tr('invalidExport', 'Die Antwort ist kein gültiger JSON-Geschäftsdatenexport.'));
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      try {
        link.href = url;
        link.download = `immomanager_business_export_${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        URL.revokeObjectURL(url);
      }
    } catch (cause) { fail(tr('exportFailed', 'Export fehlgeschlagen'), cause); }
    finally { finish(); }
  };

  const handleImport = async event => {
    const file = event.target.files?.[0];
    if (!file || !begin('import', true)) return;
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await api.postForm('/data/import', formData);
      if (!isObject(result) || !isObject(result.imported)
        || !Object.values(result.imported).every(value => Number.isSafeInteger(value) && value >= 0)
        || !Array.isArray(result.errors)) {
        throw new Error(tr('invalidImport', 'Die Serverantwort bestätigt keinen gültigen Import.'));
      }
      if (result.errors.length) {
        const rejected = new Error(tr('importRejected', 'Der Server meldet Importfehler.'));
        rejected.details = result.errors;
        throw rejected;
      }
      setImportResult(result);
      cache?.invalidateAll();
    } catch (cause) { fail(tr('importFailed', 'Import fehlgeschlagen'), cause); }
    finally {
      finish();
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">{t('pages.settings.dataBackup')}</div>
      <div className="panel-body settings-section">
        <p className="text-muted">{tr('businessScope', 'Teil-Geschäftsdaten: JSON-Datensätze ohne Anhänge, Benutzerkonten und vollständige Abrechnungsdaten.')}</p>
        <p className="text-muted">{tr('fullRecoveryHint', 'Eine vollständige, passwortverschlüsselte Sicherung von SQLite, Uploads, Benutzern und Konfiguration erfolgt offline nach dem Stoppen der Anwendung. Folgen Sie der Wartungsanleitung für vollständige Offline-Sicherungen.')}</p>
        {auth?.isReadonly && <p>{tr('readOnlyHint', 'Mit Leserechten können Sie exportieren; Sichern und Importieren erfordern Schreibrechte.')}</p>}
        {error && <div role="alert" className="alert alert-error">
          <p>{error.message}</p>
          {error.details && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
            {typeof error.details === 'string' ? error.details : JSON.stringify(error.details, null, 2)}
          </pre>}
        </div>}
        <div className="settings-row">
          <label>{t('pages.settings.database')}</label>
          <div className="settings-control">
            <span className="text-muted">{t('pages.settings.dbType')}</span>
            <button className="btn btn-sm btn-secondary" onClick={loadDbInfo} disabled={!!busy} style={{ marginLeft: '0.5rem' }}>
              {tr('info', 'Info')}
            </button>
          </div>
        </div>
        {dbInfo && <div className="settings-row">
          <label>{tr('dbDetails', 'DB-Details')}</label>
          <div className="settings-control"><span className="text-muted" style={{ fontSize: '0.8rem' }}>
            {JSON.stringify(dbInfo, null, 2).slice(0, 200)}
          </span></div>
        </div>}
        <div className="settings-row">
          <label>{tr('businessBackup', 'Teil-Geschäftsdaten sichern')}</label>
          <div className="settings-control">
            <button className="btn btn-sm btn-primary" onClick={handleBackup} disabled={!!busy || auth?.isReadonly}>
              {busy === 'backup' ? tr('backupRunning', 'Sicherung läuft…') : tr('createBackup', 'Backup erstellen')}
            </button>
            {backupResult && <span role="status" style={{ marginLeft: '0.5rem', fontSize: '0.8rem' }}>
              {tr('backupSaved', 'Teil-Geschäftsdaten gespeichert')}: {backupResult.backup} ({backupResult.size_bytes} B)
            </span>}
          </div>
        </div>
        <div className="settings-row">
          <label>{t('pages.settings.exportData')}</label>
          <div className="settings-control"><button className="btn btn-sm btn-secondary" onClick={handleExport} disabled={!!busy}>
            {busy === 'export' ? t('pages.settings.exporting') : t('pages.settings.jsonExport')}
          </button></div>
        </div>
        <div className="settings-row">
          <label htmlFor="business-data-import">{t('pages.settings.importData')}</label>
          <div className="settings-control"><input id="business-data-import" ref={fileRef} type="file" accept=".json"
            onChange={handleImport} disabled={!!busy || auth?.isReadonly} style={{ fontSize: '0.85rem' }} /></div>
        </div>
        {importResult && <div className="settings-row">
          <label>{t('pages.settings.importResult')}</label>
          <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
            <p role="status">{tr('importSaved', 'Teil-Geschäftsdaten importiert')}</p>
            {Object.entries(importResult.imported).map(([key, count]) => <span key={key} className="text-muted">
              {key}: {count} {t('pages.settings.imported')}
            </span>)}
          </div>
        </div>}
      </div>
    </div>
  );
}
