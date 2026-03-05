import { useState, useRef } from 'react';
import { usePreferences } from '../contexts/PreferencesContext';
import { useTranslation } from '../i18n';
import { api } from '../api';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const { t, locale, setLocale } = useTranslation();
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
      setBackupStatus(`${t('toasts.success.saved')}: ${result?.filename || 'OK'}`);
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
      console.warn('[Settings] export:', err.message);
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
    <div className="page">
      <h1 className="page-title">{t('pages.settings.title')}</h1>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-header">{t('pages.settings.appearance')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{t('pages.settings.theme')}</label>
              <div className="settings-control">
                <button
                  className={`btn btn-sm ${prefs.theme === 'light' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'light' && toggleTheme()}
                >{t('pages.settings.light')}</button>
                <button
                  className={`btn btn-sm ${prefs.theme === 'dark' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'dark' && toggleTheme()}
                >{t('pages.settings.dark')}</button>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.sidebar')}</label>
              <div className="settings-control">
                <button className="btn btn-sm btn-secondary" onClick={toggleSidebar}>
                  {prefs.sidebar_collapsed ? t('pages.settings.show') : t('pages.settings.hide')}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.language')}</label>
              <div className="settings-control">
                {['de-DE', 'en-US', 'es-ES'].map(loc => (
                  <button
                    key={loc}
                    className={`btn btn-sm ${locale === loc ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setLocale(loc)}
                  >{loc.slice(0, 2).toUpperCase()}</button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{t('pages.settings.tables')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{t('pages.settings.itemsPerPage')}</label>
              <div className="settings-control">
                <select
                  value={prefs.items_per_page || 25}
                  onChange={e => updatePrefs({ items_per_page: Number(e.target.value) })}
                  className="page-size-select"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.dateFormat')}</label>
              <div className="settings-control">
                <select
                  value={prefs.date_format || 'DD.MM.YYYY'}
                  onChange={e => updatePrefs({ date_format: e.target.value })}
                  className="page-size-select"
                >
                  <option value="DD.MM.YYYY">DD.MM.YYYY</option>
                  <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.currency')}</label>
              <div className="settings-control">
                <select
                  value={prefs.currency || 'EUR'}
                  onChange={e => updatePrefs({ currency: e.target.value })}
                  className="page-size-select"
                >
                  <option value="EUR">{t('pages.settings.eurLabel')}</option>
                  <option value="CHF">{t('pages.settings.chfLabel')}</option>
                  <option value="USD">{t('pages.settings.usdLabel')}</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>{tr('settings.defaultDueDay', 'Standard-Fälligkeitstag')}</label>
              <div className="settings-control">
                <select
                  value={prefs.default_due_day || 1}
                  onChange={e => updatePrefs({ default_due_day: Number(e.target.value) })}
                  className="page-size-select"
                >
                  {[1, 3, 5, 10, 15].map(d => (
                    <option key={d} value={d}>{d}.</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Benachrichtigungen</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>E-Mail-Benachrichtigungen</label>
              <div className="settings-control">
                <select
                  value={prefs.email_notifications || 'important'}
                  onChange={e => updatePrefs({ email_notifications: e.target.value })}
                  className="page-size-select"
                >
                  <option value="all">Alle</option>
                  <option value="important">Nur wichtige</option>
                  <option value="none">Keine</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>Erinnerungen</label>
              <div className="settings-control">
                <select
                  value={prefs.reminder_days || '7'}
                  onChange={e => updatePrefs({ reminder_days: e.target.value })}
                  className="page-size-select"
                >
                  <option value="3">3 Tage vorher</option>
                  <option value="7">7 Tage vorher</option>
                  <option value="14">14 Tage vorher</option>
                  <option value="30">30 Tage vorher</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{tr('settings.dataBackup.title', 'Daten & Sicherung')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{tr('settings.dataBackup.database', 'Datenbank')}</label>
              <div className="settings-control">
                <span className="text-muted">SQLite / In-Memory</span>
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
              <label>Daten exportieren</label>
              <div className="settings-control">
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={handleExport}
                  disabled={exportLoading}
                >
                  {exportLoading ? 'Exportiere...' : 'JSON-Export'}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>Daten importieren</label>
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
                <label>Import-Ergebnis</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  {importResult.imported && Object.entries(importResult.imported).map(([k, v]) => (
                    <span key={k} className="text-muted">{k}: {v} importiert</span>
                  ))}
                  {importResult.errors && Object.keys(importResult.errors).length > 0 && (
                    <span style={{ color: 'var(--danger)' }}>
                      Fehler in: {Object.keys(importResult.errors).join(', ')}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Dokumente & OCR</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Automatische OCR</label>
              <div className="settings-control">
                <span className="text-muted">Aktiv (für PDF, PNG, JPG, TIFF)</span>
              </div>
            </div>
            <div className="settings-row">
              <label>OCR-Sprachen</label>
              <div className="settings-control">
                <span className="text-muted">Deutsch + Englisch</span>
              </div>
            </div>
            <div className="settings-row">
              <label>Dateispeicher</label>
              <div className="settings-control">
                <span className="text-muted">Lokal (uploads/)</span>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">{tr('settings.about.title', 'Über ImmoManager Pro')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Version</label>
              <div className="settings-control">
                <span className="text-muted">1.0.0</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{tr('settings.about.type', 'Typ')}</label>
              <div className="settings-control">
                <span className="text-muted">{tr('settings.about.localApp', 'Lokale Anwendung (Non-Cloud, Privat)')}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
