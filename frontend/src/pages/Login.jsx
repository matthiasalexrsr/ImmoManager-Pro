import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getRegistrationStatus, login, register } from '../api';
import { useTranslation } from '../i18n';
import BrandMark from '../components/BrandMark';

export default function Login() {
  const { t } = useTranslation();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [totpRequired, setTotpRequired] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [registration, setRegistration] = useState({ open: false, initial_setup: false });
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    getRegistrationStatus().then((status) => {
      if (cancelled) return;
      setRegistration(status);
      // On a fresh install the first account is the owner: start in sign-up mode.
      if (status.initial_setup) setIsRegister(true);
    });
    return () => { cancelled = true; };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (isRegister) {
        await register(username, email, fullName, password);
      }
      if (totpRequired) await login(username, password, totpCode);
      else await login(username, password);
      navigate('/');
    } catch (err) {
      if (err.requiresTotp) { setTotpRequired(true); setTotpCode(''); }
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <div className="login-logo"><BrandMark /></div>
          <h1>ImmoManager <span className="pro">Pro</span></h1>
        </div>
        <form onSubmit={handleSubmit}>
          {error && <div className="alert-error" role="alert">{error}</div>}
          {isRegister && registration.initial_setup && (
            <div className="alert-info">{t('auth.register.initialSetup')}</div>
          )}
          <div className="form-group">
            <label htmlFor="login-username">{isRegister ? t('auth.login.username') : t('auth.login.userOrEmail')}</label>
            <input id="login-username" type="text" value={username} onChange={e => setUsername(e.target.value)} required autoFocus disabled={totpRequired || loading}
              autoComplete="username" />
          </div>
          {isRegister && (
            <>
              <div className="form-group">
                <label htmlFor="login-email">{t('auth.register.email')}</label>
                <input id="login-email" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
              </div>
              <div className="form-group">
                <label htmlFor="login-full-name">{t('auth.register.firstName')}</label>
                <input id="login-full-name" type="text" value={fullName} onChange={e => setFullName(e.target.value)} required autoComplete="name" />
              </div>
            </>
          )}
          <div className="form-group">
            <label htmlFor="login-password">{t('auth.login.password')}</label>
            {/* password managers fill a sign-in and offer a generated password when registering */}
            <input id="login-password" type="password" autoComplete={isRegister ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} required minLength={8} disabled={totpRequired || loading} placeholder={t('auth.password.placeholder') || 'Mindestens 8 Zeichen'} />
            <small className="form-hint">{t('auth.password.requirements') || 'Mindestens 8 Zeichen, 1 Großbuchstabe, 1 Kleinbuchstabe, 1 Zahl'}</small>
          </div>
          {totpRequired && <div className="form-group">
            <label htmlFor="login-totp">Zwei-Faktor-Code</label>
            <input id="login-totp" autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}"
              maxLength={6} required value={totpCode} disabled={loading} onChange={event => setTotpCode(event.target.value.replace(/\D/g, ''))} />
            <small className="form-hint">Den aktuellen sechsstelligen Code aus Ihrer Authenticator-App eingeben.</small>
            <button type="button" className="link-btn" disabled={loading}
              onClick={() => { setTotpRequired(false); setTotpCode(''); setPassword(''); setError(null); }}>Zurück zur Passworteingabe</button>
          </div>}
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? `${t('ui.table.loading')}` : (isRegister ? t('auth.register.submit') : t('auth.login.submit'))}
          </button>
        </form>
        <p className="login-toggle"><a href="/api/v1/legal" target="_blank" rel="noopener noreferrer">Lizenzen und Quellarchive</a></p>
        {registration.open && !registration.initial_setup && (
          <p className="login-toggle">
            <button disabled={loading} onClick={() => { setIsRegister(!isRegister); setError(null); setTotpRequired(false); setTotpCode(''); }} className="link-btn">
              {isRegister ? t('auth.login.submit') : t('auth.register.title')}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
