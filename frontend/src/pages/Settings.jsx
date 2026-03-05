import { useState } from 'react';
import { usePreferences } from '../contexts/PreferencesContext';
import { useTranslation } from '../i18n';
import { api } from '../api';

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const { t, locale, setLocale } = useTranslation();
  const [backupStatus, setBackupStatus] = useState(null);
  const [dbInfo, setDbInfo] = useState(null);

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

  return (
    <div className="page">
      <h1 className="page-title">{t('navigation.main.settings')}</h1>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-header">{t('settings.areas.general')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Theme</label>
              <div className="settings-control">
                <button
                  className={`btn btn-sm ${prefs.theme === 'light' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'light' && toggleTheme()}
                >{tr('settings.theme.light', 'Hell')}</button>
                <button
                  className={`btn btn-sm ${prefs.theme === 'dark' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'dark' && toggleTheme()}
                >{tr('settings.theme.dark', 'Dunkel')}</button>
              </div>
            </div>
            <div className="settings-row">
              <label>Sidebar</label>
              <div className="settings-control">
                <button className="btn btn-sm btn-secondary" onClick={toggleSidebar}>
                  {prefs.sidebar_collapsed ? tr('settings.sidebar.show', 'Einblenden') : tr('settings.sidebar.hide', 'Ausblenden')}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.general.language')}</label>
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
          <div className="panel-header">{tr('settings.tables.title', 'Tabellen')}</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>{t('ui.table.rowsPerPage')}</label>
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
              <label>{t('settings.general.dateFormat')}</label>
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
              <label>{t('settings.general.currency')}</label>
              <div className="settings-control">
                <select
                  value={prefs.currency || 'EUR'}
                  onChange={e => updatePrefs({ currency: e.target.value })}
                  className="page-size-select"
                >
                  <option value="EUR">Euro (€)</option>
                  <option value="CHF">CHF (Fr.)</option>
                  <option value="USD">USD ($)</option>
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
