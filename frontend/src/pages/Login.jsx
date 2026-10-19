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
      await login(username, password);
      navigate('/');
    } catch (err) {
      setError(err.message);
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
          {error && <div className="alert-error">{error}</div>}
          {isRegister && registration.initial_setup && (
            <div className="alert-info">{t('auth.register.initialSetup')}</div>
          )}
          <div className="form-group">
            <label htmlFor="login-username">{isRegister ? t('auth.login.username') : t('auth.login.userOrEmail')}</label>
            <input id="login-username" type="text" value={username} onChange={e => setUsername(e.target.value)} required autoFocus
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
            <input id="login-password" type="password" autoComplete={isRegister ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} required minLength={8} placeholder={t('auth.password.placeholder') || 'Mindestens 8 Zeichen'} />
            <small className="form-hint">{t('auth.password.requirements') || 'Mindestens 8 Zeichen, 1 Großbuchstabe, 1 Kleinbuchstabe, 1 Zahl'}</small>
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? `${t('ui.table.loading')}` : (isRegister ? t('auth.register.submit') : t('auth.login.submit'))}
          </button>
        </form>
        {registration.open && !registration.initial_setup && (
          <p className="login-toggle">
            <button onClick={() => { setIsRegister(!isRegister); setError(null); }} className="link-btn">
              {isRegister ? t('auth.login.submit') : t('auth.register.title')}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
