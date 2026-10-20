import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import SecuritySection from './settings/SecuritySection';
import { useTutorial } from '../components/Tutorial';
import SettingsCatalogue from './settings/SettingsCatalogue';
import { useSearchParams } from 'react-router-dom';
import { useDevMode } from '../contexts/DevModeContext';
import { useTranslation } from '../i18n';
import { useToast } from '../components/Toast';
import { api } from '../api';
import UpdateSection from './settings/UpdateSection';
import AutotestSection from './settings/AutotestSection';
import BackupSection from './settings/BackupSection';
import OperationsSection from './settings/OperationsSection';
import UsersSection from './settings/UsersSection';
import LetterheadSection from '../features/letters/LetterheadSection';

export default function Settings() {
  const [params] = useSearchParams();
  const auth = useAuth();
  const tutorial = useTutorial();
  const devMode = useDevMode();
  const { t } = useTranslation();
  const toast = useToast();
  const isAdmin = auth?.isAdmin;
  const [versionInfo, setVersionInfo] = useState(null);
  const [settingsTab, setSettingsTab] = useState(params.get('section') || 'catalogue');

  useEffect(() => { if (params.get('section')) setSettingsTab(params.get('section')); }, [params]);

  // Only admins may read /admin/version. Load once: the error toast re-renders the page, and
  // with toast/t as dependencies a refused request turned into an endless request loop.
  useEffect(() => {
    if (!isAdmin) return;
    api.get('/admin/version').then(setVersionInfo).catch(() => {
      toast.error(t('pages.settings.versionError') || 'Versionsinformationen konnten nicht geladen werden');
    });
  }, [isAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  const tr = (key, fallback) => { const value = t(key); return value === key ? fallback : value; };

  const tabs = [
    { key: 'catalogue', label: 'Einstellungen finden' },
    { key: 'letterhead', label: 'Briefkopf' },
    { key: 'security', label: 'Sicherheit / MFA' },
    { key: 'system', label: t('pages.settings.tabSystem') || 'System' },
    ...(isAdmin ? [{ key: 'users', label: t('pages.settings.users.tab') }] : []),
    ...(isAdmin ? [{ key: 'dev', label: t('pages.settings.tabDev') || 'Entwicklung' }] : []),
  ];

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.settings.title')}</h1>

      <div className="tab-bar" style={{ marginBottom: '1.25rem' }}>
        {tabs.map(tab => (
          <button
            key={tab.key}
            className={`detail-tab ${settingsTab === tab.key ? 'active' : ''}`}
            onClick={() => setSettingsTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="settings-grid">
        {settingsTab === 'catalogue' && <><SettingsCatalogue /><button className="btn btn-secondary" onClick={() => tutorial?.start(0)}>Bedienungstour starten</button></>}
        {settingsTab === 'letterhead' && <LetterheadSection />}
        {settingsTab === 'security' && <SecuritySection />}

        {settingsTab === 'users' && isAdmin && <UsersSection currentUser={auth?.user} />}

        {/* System tab: Backup, Updates, About */}
        {settingsTab === 'system' && (
          <>
            {isAdmin && <BackupSection />}
            {isAdmin && <OperationsSection />}
            {isAdmin && <UpdateSection versionInfo={versionInfo} />}

            <div className="panel">
              <div className="panel-header">{tr('settings.about.title', 'Über ImmoManager Pro')}</div>
              <div className="panel-body settings-section">
                <div className="settings-row">
                  <label>Version</label>
                  <div className="settings-control">
                    <span className="text-muted">{versionInfo?.version || (isAdmin ? '…' : '—')}</span>
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
          </>
        )}

        {/* Dev tab: Developer Mode, Autotest (admin only) */}
        {settingsTab === 'dev' && isAdmin && (
          <>
            <div className="panel">
              <div className="panel-header">{tr('devMode.title', 'Developer Mode')}</div>
              <div className="panel-body settings-section">
                <div className="settings-row">
                  <label>{tr('devMode.description', 'Annotations and improvement notes for developers')}</label>
                  <div className="settings-control">
                    <button
                      className={`btn btn-sm ${devMode?.enabled ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => devMode?.toggle()}
                      disabled={!devMode?.available}
                      title={devMode?.available ? undefined : tr('devMode.unavailable', 'Disabled in production')}
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
            </div>

            {devMode?.enabled && <AutotestSection />}
          </>
        )}
      </div>
    </div>
  );
}
