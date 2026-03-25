import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { usePreferences } from '../contexts/PreferencesContext';
import { useDevMode } from '../contexts/DevModeContext';
import { useTranslation } from '../i18n';
import { useToast } from '../components/Toast';
import { api } from '../api';
import UpdateSection from './settings/UpdateSection';
import AutotestSection from './settings/AutotestSection';
import BackupSection from './settings/BackupSection';

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const auth = useAuth();
  const devMode = useDevMode();
  const { t, locale, setLocale } = useTranslation();
  const toast = useToast();
  const isAdmin = auth?.isAdmin;
  const [versionInfo, setVersionInfo] = useState(null);

  useEffect(() => {
    api.get('/admin/version').then(setVersionInfo).catch(() => { toast.error('Versionsinformationen konnten nicht geladen werden'); });
  }, [toast]);

  const tr = (key, fallback) => {
    const result = t(key);
    return result === key ? fallback : result;
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

        {isAdmin && <BackupSection />}

        {isAdmin && <UpdateSection versionInfo={versionInfo} />}

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

        {isAdmin && devMode?.enabled && <AutotestSection />}

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
