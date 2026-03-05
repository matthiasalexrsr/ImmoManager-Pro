import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register } from '../api';
import { useTranslation } from '../i18n';

export default function Login() {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const { t } = useTranslation();
  const navigate = useNavigate();

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
          <div className="login-logo">IM</div>
          <h1>ImmoManager <span className="pro">Pro</span></h1>
          <p>{t('pages.login.subtitle')}</p>
        </div>
        <form onSubmit={handleSubmit}>
          {error && <div className="alert-error">{error}</div>}
          <div className="form-group">
            <label>{t('pages.login.username')}</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} required autoFocus placeholder={t('pages.login.usernamePlaceholder')} />
          </div>
          {isRegister && (
            <>
              <div className="form-group">
                <label>{t('pages.login.email')}</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder={t('pages.login.emailPlaceholder')} />
              </div>
              <div className="form-group">
                <label>{t('pages.login.fullName')}</label>
                <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} required placeholder={t('pages.login.fullNamePlaceholder')} />
              </div>
            </>
          )}
          <div className="form-group">
            <label>{t('pages.login.password')}</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} placeholder={t('pages.login.passwordPlaceholder')} />
            {isRegister && (
              <small className="form-hint">{t('pages.login.passwordHint')}</small>
            )}
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? t('pages.login.pleaseWait') : (isRegister ? t('pages.login.registerAndLogin') : t('pages.login.loginBtn'))}
          </button>
        </form>
        <p className="login-toggle">
          {isRegister ? t('pages.login.alreadyRegistered') : t('pages.login.noAccount')}{' '}
          <button onClick={() => { setIsRegister(!isRegister); setError(null); }} className="link-btn">
            {isRegister ? t('pages.login.loginLink') : t('pages.login.registerLink')}
          </button>
        </p>
      </div>
    </div>
  );
}
