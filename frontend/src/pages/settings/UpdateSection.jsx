import { useState } from 'react';
import { useTranslation } from '../../i18n';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import { api } from '../../api';

export default function UpdateSection({ versionInfo }) {
  const { t } = useTranslation();
  const toast = useToast();
  const confirm = useConfirm();

  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateApplying, setUpdateApplying] = useState(false);
  const [updateResult, setUpdateResult] = useState(null);
  const [updateHistory, setUpdateHistory] = useState(null);

  const tr = (key, fallback) => {
    const result = t(key);
    return result === key ? fallback : result;
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
    if (!await confirm(tr('settings.update.confirmApply', 'Update jetzt anwenden? Es wird automatisch ein Backup erstellt.'))) return;
    setUpdateApplying(true);
    setUpdateResult(null);
    try {
      const data = await api.post('/updates/apply', {
        target_version: updateInfo?.latest_version || null,
      });
      setUpdateResult(data);
      if (data.restart_required) {
        api.post('/updates/restart').catch(() => { toast.error('Neustart konnte nicht ausgelöst werden'); });
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

  return (
    <div className="panel">
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
    </div>
  );
}
