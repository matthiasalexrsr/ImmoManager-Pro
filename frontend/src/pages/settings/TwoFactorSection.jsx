import { useEffect, useState } from 'react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';

export default function TwoFactorSection() {
  const { t } = useTranslation();
  const auth = useAuth();
  const [enabled, setEnabled] = useState(null);
  const [enrollment, setEnrollment] = useState(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const text = key => t(`auth.twoFactor.${key}`);

  useEffect(() => {
    const controller = new AbortController();
    setEnabled(null);
    setStatusError(null);
    api.get('/auth/2fa/status', { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (typeof result?.enabled !== 'boolean') throw new Error(t('auth.twoFactor.invalidStatus'));
        setEnabled(result.enabled);
      })
      .catch(err => { if (!controller.signal.aborted) setStatusError(err.message); });
    return () => controller.abort();
  }, [revision, t]);

  const act = async action => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (action === 'setup') {
        const result = await api.post('/auth/2fa/setup', {});
        if (!result?.secret || !result?.uri) throw new Error(text('invalidStatus'));
        setEnrollment(result);
        setCode('');
      } else {
        const result = await api.post(`/auth/2fa/${action}`, { code });
        if (typeof result?.enabled !== 'boolean') throw new Error(text('invalidStatus'));
        setEnabled(result.enabled);
        setEnrollment(null);
        setCode('');
        setMessage(text(result.enabled ? 'enabledSuccess' : 'disabledSuccess'));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const copySecret = async () => {
    setError(null);
    try {
      await navigator.clipboard.writeText(enrollment.secret);
      setMessage(text('copied'));
    } catch {
      setError(text('copyFailed'));
    }
  };

  return <section className="panel" aria-labelledby="two-factor-title" style={{ padding: '1rem', minWidth: 0 }}>
    <h2 id="two-factor-title" className="panel-header" style={{ margin: '0 0 0.75rem', fontSize: '1.125rem' }}>{text('title')}</h2>
    <div className="panel-body settings-section">
      <p>{text('description')}</p>
      {auth?.user?.id && <p className="form-hint" style={{ overflowWrap: 'anywhere' }}>{text('accountId')}: <code>{auth.user.id}</code></p>}
      {enabled === null && !statusError && <p role="status">{t('ui.table.loading')}</p>}
      {statusError && <div role="alert"><p>{statusError}</p>
        <button className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>{t('ui.buttons.retry')}</button>
      </div>}
      {error && <p role="alert" className="alert-error">{error}</p>}
      {message && <p role="status">{message}</p>}
      {enabled !== null && <p>{text(enabled ? 'enabled' : 'disabled')}</p>}
      {enabled === false && !enrollment && <button className="btn btn-primary" disabled={busy} onClick={() => act('setup')}>{text('setup')}</button>}
      {enrollment && <>
        <p>{text('enrollInstructions')}</p>
        <div className="form-group">
          <label htmlFor="totp-secret">{text('secret')}</label>
          <input id="totp-secret" type="text" readOnly value={enrollment.secret} onFocus={event => event.target.select()} />
          <button className="btn btn-secondary" onClick={copySecret}>{text('copy')}</button>
        </div>
        <div className="form-group">
          <label htmlFor="totp-uri">{text('uri')}</label>
          <textarea id="totp-uri" readOnly value={enrollment.uri} onFocus={event => event.target.select()} rows={3} />
        </div>
      </>}
      {(enabled || enrollment) && <form onSubmit={event => { event.preventDefault(); act(enabled ? 'disable' : 'verify'); }}>
        <div className="form-group">
          <label htmlFor="settings-totp-code">{text('code')}</label>
          <input id="settings-totp-code" type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={event => setCode(event.target.value)} required />
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>{text(enabled ? 'disable' : 'verify')}</button>
      </form>}
      <p className="form-hint">{text('recovery')}</p>
    </div>
  </section>;
}
