import { useState } from 'react';
import { useTranslation } from '../../i18n';
import { api } from '../../api';

function releaseDownloadUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password
      || url.search || url.hash || !/^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/releases\/tag\/[^/?#]+$/.test(url.pathname)) return null;
    return url.href;
  } catch { return null; }
}

export default function UpdateSection({ versionInfo }) {
  const { t } = useTranslation();

  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateHistory, setUpdateHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const downloadUrl = releaseDownloadUrl(updateInfo?.release_url);

  const tr = (key, fallback) => {
    const result = t(key);
    return result === key ? fallback : result;
  };

  const checkForUpdates = async () => {
    setUpdateChecking(true);
    setUpdateInfo(null);
    try {
      const data = await api.get('/updates/check');
      setUpdateInfo(data);
    } catch (err) {
      setUpdateInfo({ error: err.message || 'Prüfung fehlgeschlagen' });
    } finally {
      setUpdateChecking(false);
    }
  };

  const loadUpdateHistory = async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await api.get('/updates/history');
      setUpdateHistory(data.history || []);
    } catch (err) {
      setHistoryError(err.message || 'Update-Verlauf konnte nicht geladen werden.');
    } finally {
      setHistoryLoading(false);
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
              disabled={updateChecking}
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
                    fontSize: 'var(--text-sm)',
                  }}>
                    {tr('settings.update.available', 'Update verfügbar!')}
                  </span>
                )}
                {!updateInfo.update_available && updateInfo.latest_version && (
                  <span style={{
                    marginLeft: '0.5rem',
                    color: 'var(--text-muted)',
                    fontSize: 'var(--text-sm)',
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
                  <details style={{ fontSize: 'var(--text-sm)', maxWidth: '100%' }}>
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
                      fontSize: 'var(--text-xs)',
                    }}>
                      {updateInfo.release_notes}
                    </pre>
                  </details>
                </div>
              </div>
            )}

            {updateInfo.update_available && (
              <div className="settings-row" style={{ alignItems: 'flex-start' }}>
                <label>{tr('settings.update.applyLabel', 'Update installieren')}</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.5rem' }}>
                  {downloadUrl && (
                    <a className="btn btn-sm btn-primary" href={downloadUrl} target="_blank" rel="noopener noreferrer">
                      {tr('settings.update.download', 'Neue Version herunterladen')}
                    </a>
                  )}
                  {!downloadUrl && <span role="alert">Für diese Version wurde keine gültige Downloadadresse geliefert. Bitte prüfen Sie die offizielle Veröffentlichungsseite.</span>}
                  <span className="text-muted" style={{ fontSize: 'var(--text-sm)' }}>{updateInfo.download_hint || 'Beenden Sie ImmoManager Pro und installieren Sie das geprüfte neue Paket. Vor einer erforderlichen Datenbankumstellung erstellt die Anwendung ein Vollbackup. Bewahren Sie dieses für eine Wiederherstellung auf.'}</span>
                </div>
              </div>
            )}
          </>
        )}

        {updateInfo?.error && (
          <div className="settings-row">
            <label>{tr('settings.update.error', 'Fehler')}</label>
            <div className="settings-control">
              <span role="alert" style={{ color: 'var(--danger)', fontSize: 'var(--text-sm)' }}>{updateInfo.error}</span>
            </div>
          </div>
        )}

        <div className="settings-row">
          <label>{tr('settings.update.history', 'Update-Verlauf')}</label>
          <div className="settings-control">
            <button className="btn btn-sm btn-secondary" onClick={loadUpdateHistory} disabled={historyLoading}>
              {historyLoading ? 'Wird geladen…' : tr('settings.update.showHistory', 'Anzeigen')}
            </button>
          </div>
        </div>
        {historyError && <div role="alert">{historyError}</div>}
        {updateHistory && updateHistory.length > 0 && (
          <div className="settings-row" style={{ alignItems: 'flex-start' }}>
            <label></label>
            <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start', fontSize: 'var(--text-xs)' }}>
              {updateHistory.slice(0, 5).map((entry, i) => (
                <span key={i} className="text-muted" style={{ marginBottom: '0.2rem' }}>
                  {entry.timestamp?.slice(0, 10)} &mdash; {entry.from_version} &rarr; {entry.to_version}
                  {entry.success ? ' ✓' : ' ✗'}
                </span>
              ))}
            </div>
          </div>
        )}
        {!historyError && updateHistory && updateHistory.length === 0 && (
          <div className="settings-row">
            <label></label>
            <div className="settings-control">
              <span className="text-muted" style={{ fontSize: 'var(--text-sm)' }}>
                {tr('settings.update.noHistory', 'Noch keine Updates durchgeführt')}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
