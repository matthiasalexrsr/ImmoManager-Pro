import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getSetupStatus, login, setupOwner } from '../api';
import { useTranslation } from '../i18n';

export default function Login() {
  const { t } = useTranslation();
  const [setup, setSetup] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [requiresTwoFactor, setRequiresTwoFactor] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    setSetup(null);
    setStatusError(null);
    getSetupStatus({ signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (typeof result?.setup_required !== 'boolean' || typeof result?.setup_allowed !== 'boolean') throw new Error(t('auth.setup.invalidStatus'));
        setSetup(result);
      })
      .catch(err => { if (!controller.signal.aborted) setStatusError(err.message); });
    return () => controller.abort();
  }, [revision, t]);

  const isSetup = setup?.setup_required && setup?.setup_allowed;
  const blocked = setup?.setup_required && !setup?.setup_allowed;
  const handleSubmit = async event => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (isSetup) {
        await setupOwner(username, email, fullName, password);
        // Setup is committed before login. A login failure must not create another owner.
        setSetup({ ...setup, setup_required: false });
      }
      await login(username, password, totpCode);
      navigate('/');
    } catch (err) {
      if (err.requiresTwoFactor) setRequiresTwoFactor(true);
      if (isSetup && err.statusCode === 409) setRevision(value => value + 1);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <div className="login-logo">IM</div>
          <h1>ImmoManager <span className="pro">Pro</span></h1>
          <p>{isSetup ? t('auth.setup.title') : t('brand.slogan')}</p>
        </div>
        {!setup && !statusError && <p role="status">{t('ui.table.loading')}</p>}
        {statusError && <div role="alert">
          <p>{statusError}</p>
          <button className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>{t('ui.buttons.retry')}</button>
        </div>}
        {blocked && <p role="alert">{t('auth.setup.localOnly')}</p>}
        {setup && !blocked && <form onSubmit={handleSubmit}>
          {isSetup && <p>{t('auth.setup.description')}</p>}
          {error && <div className="alert-error" role="alert">{error}</div>}
          <div className="form-group">
            <label htmlFor="login-username">{t('auth.login.username')}</label>
            <input id="login-username" type="text" value={username} onChange={event => { setUsername(event.target.value); setRequiresTwoFactor(false); setTotpCode(''); }} required autoFocus autoComplete="username" />
          </div>
          {isSetup && <>
            <div className="form-group">
              <label htmlFor="setup-email">{t('auth.register.email')}</label>
              <input id="setup-email" type="email" value={email} onChange={event => setEmail(event.target.value)} required autoComplete="email" />
            </div>
            <div className="form-group">
              <label htmlFor="setup-name">{t('auth.setup.fullName')}</label>
              <input id="setup-name" type="text" value={fullName} onChange={event => setFullName(event.target.value)} required autoComplete="name" />
            </div>
          </>}
          <div className="form-group">
            <label htmlFor="login-password">{t('auth.login.password')}</label>
            <input id="login-password" type="password" value={password} onChange={event => setPassword(event.target.value)} required minLength={8} autoComplete={isSetup ? 'new-password' : 'current-password'} />
            {isSetup && <small className="form-hint">{t('auth.password.requirements')}</small>}
          </div>
          {requiresTwoFactor && <div className="form-group">
            <label htmlFor="login-totp">{t('auth.twoFactor.code')}</label>
            <input id="login-totp" type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={totpCode} onChange={event => setTotpCode(event.target.value)} required autoFocus />
          </div>}
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? t('ui.table.loading') : isSetup ? t('auth.setup.submit') : t('auth.login.submit')}
          </button>
          {!isSetup && <p className="form-hint">{t('auth.setup.approvedOnly')}</p>}
        </form>}
      </div>
    </div>
  );
}
