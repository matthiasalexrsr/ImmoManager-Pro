import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '../../i18n';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { formatBytes, formatDateTime } from '../../utils/format';
import PlatformSection from './PlatformSection';

// Operations overview: full backups, restore probes, secrets at rest (GET /admin/operations).

// Long paths and messages wrap inside the narrow settings column instead of running out of it.
const COLUMN = { flexDirection: 'column', alignItems: 'flex-start', minWidth: 0, overflowWrap: 'anywhere' };

// Literal keys on purpose: the translation test finds every one of them.
function warningText(t, warning) {
  switch (warning.code) {
    case 'schedule_disabled': return t('settings.operations.warnings.schedule_disabled');
    case 'no_second_target': return t('settings.operations.warnings.no_second_target');
    case 'second_target_failed': return t('settings.operations.warnings.second_target_failed');
    case 'second_target_pending': return t('settings.operations.warnings.second_target_pending');
    case 'second_target_same_device': return t('settings.operations.warnings.second_target_same_device');
    case 'no_backup': return t('settings.operations.warnings.no_backup');
    case 'backup_stale': return t('settings.operations.warnings.backup_stale', { hours: warning.hours });
    case 'last_backup_failed': return t('settings.operations.warnings.last_backup_failed');
    case 'no_probe': return t('settings.operations.warnings.no_probe');
    case 'probe_stale': return t('settings.operations.warnings.probe_stale', { days: warning.days });
    case 'last_probe_failed': return t('settings.operations.warnings.last_probe_failed');
    case 'keys_unprotected': return t('settings.operations.warnings.keys_unprotected', { file: warning.file || '.env' });
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

// The folder every full backup is copied to. Only the owner changes it; a folder set in the
// configuration (BACKUP_SECOND_TARGET) is shown but cannot be changed here.
function SecondTarget({ backup, canChange, busy, onSaved, t }) {
  const [draft, setDraft] = useState(null);       // null: not editing
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState(null);
  const fixed = backup.second_target_source === 'env';

  const save = async (path) => {
    setSaving(true);
    setProblem(null);
    try {
      const result = await api.put('/admin/operations/second-target', { path });
      setDraft(null);
      onSaved(result);
    } catch (err) {
      setProblem(err?.message || t('settings.operations.failed'));
    } finally {
      setSaving(false);
    }
  };

  if (draft === null) {
    return (
      <div className="settings-control" style={{ flexWrap: 'wrap', gap: '0.5rem', minWidth: 0 }}>
        <span className="text-muted" style={{ wordBreak: 'break-all' }} data-testid="second-target">
          {backup.second_target || t('settings.operations.notConfigured')}
        </span>
        {fixed && <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>{t('settings.operations.secondTargetFixed')}</span>}
        {canChange && !fixed && (
          <button type="button" className="btn btn-sm btn-secondary" disabled={busy}
                  onClick={() => setDraft(backup.second_target || '')}>
            {backup.second_target ? t('settings.operations.secondTargetChange') : t('settings.operations.secondTargetSetUp')}
          </button>
        )}
      </div>
    );
  }
  return (
    <form className="settings-control" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '0.4rem', minWidth: 0, flex: 1 }}
          onSubmit={(event) => { event.preventDefault(); save(draft); }}>
      <input type="text" className="form-control" value={draft} autoFocus disabled={saving}
             aria-label={t('settings.operations.secondTarget')}
             placeholder={t('settings.operations.secondTargetPlaceholder')}
             onChange={(event) => setDraft(event.target.value)} />
      <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>{t('settings.operations.secondTargetHint')}</span>
      {problem && <span role="alert" style={{ color: 'var(--danger)' }}>{problem}</span>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
        <button type="submit" className="btn btn-sm btn-primary" disabled={saving || !draft.trim()}>
          {saving ? t('settings.operations.running') : t('settings.operations.secondTargetSave')}
        </button>
        {backup.second_target && (
          <button type="button" className="btn btn-sm btn-secondary" disabled={saving} onClick={() => save('')}>
            {t('settings.operations.secondTargetRemove')}
          </button>
        )}
        <button type="button" className="btn btn-sm btn-secondary" disabled={saving}
                onClick={() => { setDraft(null); setProblem(null); }}>
          {t('settings.operations.secondTargetCancel')}
        </button>
      </div>
    </form>
  );
}

export default function OperationsSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const isOwner = auth?.user?.role === 'eigentuemer';
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);
  const [showPlatform, setShowPlatform] = useState(false);

  const load = useCallback(() => {
    api.get('/admin/operations')
      .then((body) => { setData(body); setError(null); })
      .catch((err) => setError(err?.message || t('settings.operations.loadError')));
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const targetSaved = (result) => {
    const text = result?.second_target
      ? t('settings.operations.secondTargetSaved', { path: result.second_target })
      : t('settings.operations.secondTargetRemoved');
    setMessage({ ok: true, text: result?.same_device
      ? `${text} ${t('settings.operations.warnings.second_target_same_device')}` : text });
    // show the folder at once; the reload brings the notices that go with it
    setData((current) => current && { ...current, backup: { ...current.backup,
      second_target: result?.second_target || null, second_target_source: result?.source || null } });
    load();
  };

  const run = async (kind) => {
    setBusy(kind);
    setMessage(null);
    try {
      const result = await api.post(kind === 'backup' ? '/admin/operations/backup' : '/admin/operations/restore-probe');
      setMessage({ ok: result?.ok !== false, text: result?.ok === false
        ? 'Archiv lesbar, aber Wiederherstellbarkeit nicht vollständig bestätigt. Bitte Prüfdetails und Geheimnissicherung prüfen.' : kind === 'backup'
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
        {isOwner && <div style={{ padding: '1rem' }}>
          <button type="button" className="btn btn-secondary" aria-expanded={showPlatform}
            onClick={() => setShowPlatform(value => !value)}>Speicher und Plugins {showPlatform ? 'schließen' : 'anzeigen'}</button>
          {showPlatform && <PlatformSection />}
        </div>}
        <p className="text-muted" style={{ margin: 0, padding: '0.75rem 1.1rem 0.25rem' }}>{t('settings.operations.intro')}</p>
        {error && <div role="alert" style={{ color: 'var(--danger)', padding: '0.5rem 1.1rem' }}>{error}</div>}
        {data && (
          <>
            <div className="settings-row">
              <label>{t('settings.operations.lastBackup')}</label>
              <div className="settings-control" style={COLUMN}>
                <Status event={lastBackup} t={t} />
                {lastBackup?.ok && (
                  <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
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
              <div className="settings-control" style={COLUMN}>
                <span className="text-muted">{t('settings.operations.archivesValue', {
                  count: backup.archives.length, size: formatBytes(backup.total_size_bytes),
                })}</span>
                <span className="text-muted" style={{ fontSize: 'var(--text-xs)', wordBreak: 'break-all' }}>{backup.directory}</span>
              </div>
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.secondTarget')}</label>
              <SecondTarget backup={backup} canChange={isOwner} busy={busy !== null} onSaved={targetSaved} t={t} />
            </div>
            <div className="settings-row">
              <label>{t('settings.operations.keys')}</label>
              <div className="settings-control" style={COLUMN}>
                <span className="text-muted">{t('settings.operations.keysValue', {
                  key: secrets?.active_key_id || '—', sealed: secrets?.sealed ?? 0, plaintext: secrets?.plaintext ?? 0,
                })}</span>
                <span className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
                  {backup.passphrase_protected ? t('settings.operations.passphraseOn') : t('settings.operations.passphraseOff')}
                </span>
              </div>
            </div>
            {data.warnings?.length > 0 && (
              <div className="settings-row">
                <label>{t('settings.operations.warningsTitle')}</label>
                <div className="settings-control" style={COLUMN}>
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }} data-testid="operations-warnings">
                    {data.warnings.map((warning) => <li key={warning.code}>{warningText(t, warning)}</li>)}
                  </ul>
                </div>
              </div>
            )}
            {data.failures?.length > 0 && (
              <div className="settings-row">
                <label>{t('settings.operations.failures')}</label>
                <div className="settings-control" style={COLUMN}>
                  {data.failures.slice(0, 5).map((failure) => (
                    <span key={`${failure.event}-${failure.at}`} className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
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
          <div role={message.ok ? 'status' : 'alert'} style={{ color: message.ok ? 'var(--success)' : 'var(--danger)',
            padding: '0.5rem 1.1rem 0.75rem', overflowWrap: 'anywhere' }}>
            {message.text}
          </div>
        )}
      </div>
    </div>
  );
}
