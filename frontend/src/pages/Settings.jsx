import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { usePreferences } from '../contexts/PreferencesContext';
import { useDevMode } from '../contexts/DevModeContext';
import { useTranslation } from '../i18n';
import { api } from '../api';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const auth = useAuth();
  const devMode = useDevMode();
  const { t, locale, setLocale } = useTranslation();
  const isAdmin = auth?.isAdmin;
  const [backupStatus, setBackupStatus] = useState(null);
  const [dbInfo, setDbInfo] = useState(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [versionInfo, setVersionInfo] = useState(null);
  const fileRef = useRef(null);

  // Update state
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateApplying, setUpdateApplying] = useState(false);
  const [updateResult, setUpdateResult] = useState(null);
  const [updateHistory, setUpdateHistory] = useState(null);

  // Autotest state
  const [autotestRunning, setAutotestRunning] = useState(false);
  const [autotestResult, setAutotestResult] = useState(null);
  const [autotestUploading, setAutotestUploading] = useState(false);
  const [autotestUploadResult, setAutotestUploadResult] = useState(null);

  useEffect(() => {
    api.get('/admin/version').then(setVersionInfo).catch(() => {});
  }, []);

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
      setBackupStatus(`Export fehlgeschlagen: ${err.message}`);
    } finally {
      setExportLoading(false);
    }
  };

  const checkForUpdates = async () => {
    setUpdateChecking(true);
    setUpdateInfo(null);
    setUpdateResult(null);
    try {
      const data = await api.get('/updates/check');
      setUpdateInfo(data);
    } catch (err) {
      setUpdateInfo({ error: err.message || 'Prüfung fehlgeschlagen' });
    } finally {
      setUpdateChecking(false);
    }
  };

  const applyUpdate = async () => {
    if (!confirm(tr('settings.update.confirmApply', 'Update jetzt anwenden? Es wird automatisch ein Backup erstellt.'))) return;
    setUpdateApplying(true);
    setUpdateResult(null);
    try {
      const data = await api.post('/updates/apply', {
        target_version: updateInfo?.latest_version || null,
      });
      setUpdateResult(data);
      if (data.restart_required) {
        api.post('/updates/restart').catch(() => {});
      }
    } catch (err) {
      setUpdateResult({ success: false, message: err.message || 'Update fehlgeschlagen' });
    } finally {
      setUpdateApplying(false);
    }
  };

  const loadUpdateHistory = async () => {
    try {
      const data = await api.get('/updates/history');
      setUpdateHistory(data.history || []);
    } catch {
      setUpdateHistory([]);
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

  // ── Autotest handlers ─────────────────────────────────────────────────

  const handleRunAutotest = async () => {
    setAutotestRunning(true);
    setAutotestResult(null);
    setAutotestUploadResult(null);
    try {
      const data = await api.post('/autotest/run');
      setAutotestResult(data);
    } catch (err) {
      setAutotestResult({ error: err.message || 'Autotest failed' });
    } finally {
      setAutotestRunning(false);
    }
  };

  const handleDownloadReport = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/autotest/report/markdown`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'AUTOTEST_REPORT.md';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('[Autotest] Download failed:', err);
    }
  };

  const handleUploadReport = async () => {
    setAutotestUploading(true);
    setAutotestUploadResult(null);
    try {
      const data = await api.post('/autotest/upload-report');
      setAutotestUploadResult(data);
    } catch (err) {
      setAutotestUploadResult({ error: err.message || 'Upload failed' });
    } finally {
      setAutotestUploading(false);
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
          <div className="panel-header">{t('pages.settings.notificationsSection')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{t('pages.settings.emailNotifications')}</label>
              <div className="settings-control">
                <select
                  value={prefs.email_notifications || 'important'}
                  onChange={e => updatePrefs({ email_notifications: e.target.value })}
                  className="page-size-select"
                >
                  <option value="all">{t('pages.settings.emailAll')}</option>
                  <option value="important">{t('pages.settings.emailImportant')}</option>
                  <option value="none">{t('pages.settings.emailNone')}</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.reminders')}</label>
              <div className="settings-control">
                <select
                  value={prefs.reminder_days || '7'}
                  onChange={e => updatePrefs({ reminder_days: e.target.value })}
                  className="page-size-select"
                >
                  <option value="3">{t('pages.settings.days3')}</option>
                  <option value="7">{t('pages.settings.days7')}</option>
                  <option value="14">{t('pages.settings.days14')}</option>
                  <option value="30">{t('pages.settings.days30')}</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {isAdmin && (<div className="panel">
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
        </div>)}

        {isAdmin && (<div className="panel">
          <div className="panel-header">{tr('settings.update.title', 'Updates')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{tr('settings.update.currentVersion', 'Aktuelle Version')}</label>
              <div className="settings-control">
                <span className="text-muted">{versionInfo?.version || '...'}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{tr('settings.update.checkLabel', 'Auf Updates prüfen')}</label>
              <div className="settings-control">
                <button
                  className="btn btn-sm btn-primary"
                  onClick={checkForUpdates}
                  disabled={updateChecking || updateApplying}
                >
                  {updateChecking
                    ? tr('settings.update.checking', 'Prüfe...')
                    : tr('settings.update.checkNow', 'Jetzt prüfen')}
                </button>
              </div>
            </div>

            {updateInfo && !updateInfo.error && (
              <>
                <div className="settings-row">
                  <label>{tr('settings.update.latestVersion', 'Neueste Version')}</label>
                  <div className="settings-control">
                    <span className="text-muted">{updateInfo.latest_version || '—'}</span>
                    {updateInfo.update_available && (
                      <span style={{
                        marginLeft: '0.5rem',
                        color: 'var(--success, #22c55e)',
                        fontWeight: 600,
                        fontSize: '0.85rem',
                      }}>
                        {tr('settings.update.available', 'Update verfügbar!')}
                      </span>
                    )}
                    {!updateInfo.update_available && updateInfo.latest_version && (
                      <span style={{
                        marginLeft: '0.5rem',
                        color: 'var(--text-muted)',
                        fontSize: '0.85rem',
                      }}>
                        {tr('settings.update.upToDate', 'Bereits aktuell')}
                      </span>
                    )}
                  </div>
                </div>

                {updateInfo.release_notes && (
                  <div className="settings-row">
                    <label>{tr('settings.update.releaseNotes', 'Release-Hinweise')}</label>
                    <div className="settings-control">
                      <details style={{ fontSize: '0.85rem', maxWidth: '100%' }}>
                        <summary style={{ cursor: 'pointer', color: 'var(--primary)' }}>
                          {tr('settings.update.showNotes', 'Anzeigen')}
                        </summary>
                        <pre style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          background: 'var(--bg-secondary, #f3f4f6)',
                          padding: '0.5rem',
                          borderRadius: '4px',
                          marginTop: '0.5rem',
                          maxHeight: '200px',
                          overflow: 'auto',
                          fontSize: '0.8rem',
                        }}>
                          {updateInfo.release_notes}
                        </pre>
                      </details>
                    </div>
                  </div>
                )}

                {updateInfo.update_available && (
                  <div className="settings-row">
                    <label>{tr('settings.update.applyLabel', 'Update installieren')}</label>
                    <div className="settings-control">
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={applyUpdate}
                        disabled={updateApplying || updateInfo.is_frozen}
                        title={updateInfo.is_frozen ? 'Im Bundle-Modus nicht verfügbar' : ''}
                      >
                        {updateApplying
                          ? tr('settings.update.applying', 'Wird installiert...')
                          : tr('settings.update.applyNow', 'Jetzt installieren')}
                      </button>
                      {updateInfo.is_frozen && (
                        <span className="text-muted" style={{ marginLeft: '0.5rem', fontSize: '0.8rem' }}>
                          {tr('settings.update.frozenHint', 'Im Bundle-Modus nicht verfügbar')}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}

            {updateInfo?.error && (
              <div className="settings-row">
                <label>{tr('settings.update.error', 'Fehler')}</label>
                <div className="settings-control">
                  <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>{updateInfo.error}</span>
                </div>
              </div>
            )}

            {updateResult && (
              <div className="settings-row" style={{ alignItems: 'flex-start' }}>
                <label>{tr('settings.update.result', 'Ergebnis')}</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  <span style={{
                    fontWeight: 600,
                    color: updateResult.success ? 'var(--success, #22c55e)' : 'var(--danger)',
                    fontSize: '0.85rem',
                  }}>
                    {updateResult.message}
                  </span>
                  {updateResult.steps && updateResult.steps.length > 0 && (
                    <details style={{ marginTop: '0.5rem', fontSize: '0.8rem', width: '100%' }}>
                      <summary style={{ cursor: 'pointer', color: 'var(--primary)' }}>
                        {tr('settings.update.showSteps', 'Schritte anzeigen')} ({updateResult.steps.length})
                      </summary>
                      <ul style={{ margin: '0.5rem 0', paddingLeft: '1.2rem' }}>
                        {updateResult.steps.map((step, i) => (
                          <li key={i} style={{ marginBottom: '0.2rem' }}>{step}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {updateResult.restart_required && (
                    <span style={{
                      marginTop: '0.5rem',
                      padding: '0.4rem 0.8rem',
                      background: 'var(--warning-bg, #fef3c7)',
                      color: 'var(--warning-text, #92400e)',
                      borderRadius: '4px',
                      fontSize: '0.85rem',
                    }}>
                      {tr('settings.update.restartRequired', 'Bitte starten Sie die Anwendung neu, um das Update zu aktivieren.')}
                    </span>
                  )}
                  {updateResult.rollback_performed && (
                    <span style={{
                      marginTop: '0.5rem',
                      padding: '0.4rem 0.8rem',
                      background: 'var(--danger-bg, #fef2f2)',
                      color: 'var(--danger, #dc2626)',
                      borderRadius: '4px',
                      fontSize: '0.85rem',
                    }}>
                      {tr('settings.update.rolledBack', 'Automatischer Rollback wurde durchgeführt. Ihre Daten sind unverändert.')}
                    </span>
                  )}
                </div>
              </div>
            )}

            <div className="settings-row">
              <label>{tr('settings.update.history', 'Update-Verlauf')}</label>
              <div className="settings-control">
                <button className="btn btn-sm btn-secondary" onClick={loadUpdateHistory}>
                  {tr('settings.update.showHistory', 'Anzeigen')}
                </button>
              </div>
            </div>
            {updateHistory && updateHistory.length > 0 && (
              <div className="settings-row" style={{ alignItems: 'flex-start' }}>
                <label></label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start', fontSize: '0.8rem' }}>
                  {updateHistory.slice(0, 5).map((entry, i) => (
                    <span key={i} className="text-muted" style={{ marginBottom: '0.2rem' }}>
                      {entry.timestamp?.slice(0, 10)} &mdash; {entry.from_version} &rarr; {entry.to_version}
                      {entry.success ? ' ✓' : ' ✗'}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {updateHistory && updateHistory.length === 0 && (
              <div className="settings-row">
                <label></label>
                <div className="settings-control">
                  <span className="text-muted" style={{ fontSize: '0.85rem' }}>
                    {tr('settings.update.noHistory', 'Noch keine Updates durchgeführt')}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>)}

        <div className="panel">
          <div className="panel-header">{t('pages.settings.docsOcr')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{t('pages.settings.autoOcr')}</label>
              <div className="settings-control">
                <span className="text-muted">{t('pages.settings.ocrActive')}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.ocrLanguages')}</label>
              <div className="settings-control">
                <span className="text-muted">{t('pages.settings.ocrLangs')}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('pages.settings.fileStorage')}</label>
              <div className="settings-control">
                <span className="text-muted">{t('pages.settings.fileStorageLocal')}</span>
              </div>
            </div>
          </div>
        </div>

        {isAdmin && (<div className="panel">
          <div className="panel-header">{tr('devMode.title', 'Developer Mode')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{tr('devMode.description', 'Annotations and improvement notes for developers')}</label>
              <div className="settings-control">
                <button
                  className={`btn btn-sm ${devMode?.enabled ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => devMode?.toggle()}
                >
                  {devMode?.enabled
                    ? tr('devMode.disable', 'Disable Developer Mode')
                    : tr('devMode.enable', 'Enable Developer Mode')}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>{tr('devMode.shortcut', 'Shortcut')}</label>
              <div className="settings-control">
                <span className="text-muted">Ctrl+Shift+D</span>
              </div>
            </div>
          </div>
        </div>)}

        {isAdmin && devMode?.enabled && (
        <div className="panel">
          <div className="panel-header">Autotest — Self-Diagnostic Suite</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Run the full automated test suite against the application</label>
              <div className="settings-control">
                <button
                  className="btn btn-sm btn-primary"
                  onClick={handleRunAutotest}
                  disabled={autotestRunning}
                >
                  {autotestRunning ? 'Running Tests...' : 'Run Autotest'}
                </button>
              </div>
            </div>

            {autotestResult && !autotestResult.error && (
              <>
                <div className="settings-row">
                  <label>Result</label>
                  <div className="settings-control">
                    <span style={{
                      color: autotestResult.summary?.failed > 0 ? 'var(--color-danger, #dc3545)' : 'var(--color-success, #28a745)',
                      fontWeight: 600,
                    }}>
                      {autotestResult.summary?.passed}/{autotestResult.summary?.total} passed
                      {autotestResult.summary?.failed > 0 && ` — ${autotestResult.summary.failed} FAILED`}
                      {autotestResult.summary?.warnings > 0 && ` — ${autotestResult.summary.warnings} warnings`}
                    </span>
                  </div>
                </div>

                <div className="settings-row">
                  <label>Duration</label>
                  <div className="settings-control">
                    <span className="text-muted">{Math.round(autotestResult.duration_ms || 0)}ms</span>
                  </div>
                </div>

                {autotestResult.modules?.map((mod) => (
                  <div key={mod.name} className="settings-row" style={{ borderLeft: mod.failed > 0 ? '3px solid var(--color-danger, #dc3545)' : '3px solid var(--color-success, #28a745)', paddingLeft: '8px' }}>
                    <label style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>{mod.name}</label>
                    <div className="settings-control">
                      <span className="text-muted" style={{ fontSize: '0.85em' }}>
                        {mod.passed} passed, {mod.failed} failed
                        {mod.warnings > 0 && `, ${mod.warnings} warnings`}
                        {' '}({Math.round(mod.duration_ms)}ms)
                      </span>
                    </div>
                  </div>
                ))}

                <div className="settings-row">
                  <label>Download Report</label>
                  <div className="settings-control" style={{ display: 'flex', gap: '8px' }}>
                    <button className="btn btn-sm btn-secondary" onClick={handleDownloadReport}>
                      Download Markdown
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={handleUploadReport}
                      disabled={autotestUploading}
                    >
                      {autotestUploading ? 'Uploading...' : 'Upload to GitHub'}
                    </button>
                  </div>
                </div>

                {autotestUploadResult && (
                  <div className="settings-row">
                    <label>Upload Status</label>
                    <div className="settings-control">
                      {autotestUploadResult.error ? (
                        <span style={{ color: 'var(--color-danger, #dc3545)' }}>{autotestUploadResult.error}</span>
                      ) : (
                        <span style={{ color: 'var(--color-success, #28a745)' }}>
                          {autotestUploadResult.message}
                          {autotestUploadResult.html_url && (
                            <> — <a href={autotestUploadResult.html_url} target="_blank" rel="noopener noreferrer">View on GitHub</a></>
                          )}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}

            {autotestResult?.error && (
              <div className="settings-row">
                <label>Error</label>
                <div className="settings-control">
                  <span style={{ color: 'var(--color-danger, #dc3545)' }}>{autotestResult.error}</span>
                </div>
              </div>
            )}
          </div>
        </div>
        )}

        <div className="panel">
          <div className="panel-header">{tr('settings.about.title', 'Über ImmoManager Pro')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Version</label>
              <div className="settings-control">
                <span className="text-muted">{versionInfo?.version || '...'}</span>
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
