import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '../../i18n';
import { api } from '../../api';
import { formatBytes, formatDateTime } from '../../utils/format';

// Operations overview: full backups, restore probes, secrets at rest (GET /admin/operations).

// Literal keys on purpose: the translation test finds every one of them.
function warningText(t, warning) {
  switch (warning.code) {
    case 'schedule_disabled': return t('settings.operations.warnings.schedule_disabled');
    case 'no_second_target': return t('settings.operations.warnings.no_second_target');
    case 'second_target_failed': return t('settings.operations.warnings.second_target_failed');
    case 'no_backup': return t('settings.operations.warnings.no_backup');
    case 'backup_stale': return t('settings.operations.warnings.backup_stale', { hours: warning.hours });
    case 'last_backup_failed': return t('settings.operations.warnings.last_backup_failed');
    case 'no_probe': return t('settings.operations.warnings.no_probe');
    case 'probe_stale': return t('settings.operations.warnings.probe_stale', { days: warning.days });
    case 'last_probe_failed': return t('settings.operations.warnings.last_probe_failed');
    case 'keys_unprotected': return t('settings.operations.warnings.keys_unprotected');
    case 'keys_not_in_backup':
      return t('settings.operations.warnings.keys_not_in_backup', { ids: (warning.ids || []).join(', ') });
    case 'plaintext_secrets': return t('settings.operations.warnings.plaintext_secrets', { count: warning.count });
    case 'secrets_error': return t('settings.operations.warnings.secrets_error');
    case 'schema_not_current': return t('settings.operations.warnings.schema_not_current');
    default: return warning.code;
  }
}

function Status({ event, t }) {
  if (!event) return <span className="text-muted">{t('settings.operations.never')}</span>;
  return (
    <span>
      <span className={`badge ${event.ok ? 'paid' : 'overdue'}`}>
        {event.ok ? t('settings.operations.ok') : t('settings.operations.failed')}
      </span>{' '}
      <span className="text-muted">{formatDateTime(event.at)}</span>
      {event.error && <span role="alert" style={{ color: 'var(--danger)', display: 'block' }}>{event.error}</span>}
    </span>
  );
}

export default function OperationsSection() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);

  const load = useCallback(() => {
    api.get('/admin/operations')
      .then((body) => { setData(body); setError(null); })
      .catch((err) => setError(err?.message || t('settings.operations.loadError')));
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const run = async (kind) => {
    setBusy(kind);
    setMessage(null);
    try {
      const result = await api.post(kind === 'backup' ? '/admin/operations/backup' : '/admin/operations/restore-probe');
      setMessage({ ok: true, text: kind === 'backup'
        ? t('settings.operations.backupDone', { name: result?.archive || '' })
        : t('settings.operations.probeDone', { name: result?.archive || '' }) });
    } catch (err) {
      setMessage({ ok: false, text: err?.message || t('settings.operations.failed') });
    } finally {
      setBusy(null);
      load();
    }
  };

  const backup = data?.backup;
  const probe = data?.restore_probe;
  const secrets = data?.secrets;
  const lastBackup = backup?.last;

  return (
    <div className="panel" data-testid="operations-section">
      <div className="panel-header">{t('settings.operations.title')}</div>
      <div className="panel-body settings-section">
        <p className="text-muted" style={{ marginTop: 0 }}>{t('settings.operations.intro')}</p>
        {error && <div role="alert" style={{ color: 'var(--danger)' }}>{error}</div>}
        {data && (
          <>
            <div className="settings-row">
              <label>{t('settings.operations.lastBackup')}</label>
              <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                <Status event={lastBackup} t={t} />
                {lastBackup?.ok && (
                  <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                    {lastBackup.archive} · {formatBytes(lastBackup.size)}
                  </span>
                )}
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.lastProbe')}</label>
              <div className="settings-control"><Status event={probe?.last} t={t} /></div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.schedule')}</label>
              <div className="settings-control">
                <span className="text-muted">
                  {backup.enabled
                    ? t('settings.operations.scheduleValue', {
                      time: backup.schedule.daily_at, day: probe.schedule.day, probeTime: probe.schedule.at,
                      tz: backup.schedule.timezone,
                    })
                    : t('settings.operations.scheduleOff')}
                </span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.retention')}</label>
              <div className="settings-control">
                <span className="text-muted">{t('settings.operations.retentionValue', {
                  daily: backup.retention.daily, monthly: backup.retention.monthly,
                  preUpgrade: backup.retention.pre_upgrade,
                })}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.archives')}</label>
              <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                <span className="text-muted">{t('settings.operations.archivesValue', {
                  count: backup.archives.length, size: formatBytes(backup.total_size_bytes),
                })}</span>
                <span className="text-muted" style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>{backup.directory}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.secondTarget')}</label>
              <div className="settings-control">
                <span className="text-muted" style={{ wordBreak: 'break-all' }}>
                  {backup.second_target || t('settings.operations.notConfigured')}
                </span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.keys')}</label>
              <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                <span className="text-muted">{t('settings.operations.keysValue', {
                  key: secrets?.active_key_id || '—', sealed: secrets?.sealed ?? 0, plaintext: secrets?.plaintext ?? 0,
                })}</span>
                <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                  {backup.passphrase_protected ? t('settings.operations.passphraseOn') : t('settings.operations.passphraseOff')}
                </span>
              </div>
            </div>
            {data.warnings?.length > 0 && (
              <div className="settings-row">
                <label>{t('settings.operations.warningsTitle')}</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }} data-testid="operations-warnings">
                    {data.warnings.map((warning) => <li key={warning.code}>{warningText(t, warning)}</li>)}
                  </ul>
                </div>
              </div>
            )}
            {data.failures?.length > 0 && (
              <div className="settings-row">
                <label>{t('settings.operations.failures')}</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  {data.failures.slice(0, 5).map((failure) => (
                    <span key={`${failure.event}-${failure.at}`} className="text-muted" style={{ fontSize: '0.8rem' }}>
                      {formatDateTime(failure.at)} · {failure.event} · {failure.error}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        <div className="settings-row">
          <label>{t('settings.operations.actions')}</label>
          <div className="settings-control" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
            <button type="button" className="btn btn-sm btn-primary" disabled={busy !== null} onClick={() => run('backup')}>
              {busy === 'backup' ? t('settings.operations.running') : t('settings.operations.runBackup')}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" disabled={busy !== null} onClick={() => run('probe')}>
              {busy === 'probe' ? t('settings.operations.running') : t('settings.operations.runProbe')}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" disabled={busy !== null} onClick={load}>
              {t('settings.operations.refresh')}
            </button>
          </div>
        </div>
        {message && (
          <div role={message.ok ? 'status' : 'alert'} style={{ color: message.ok ? 'var(--success)' : 'var(--danger)' }}>
            {message.text}
          </div>
        )}
      </div>
    </div>
  );
}
