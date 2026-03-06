import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register } from '../api';
import { useTranslation } from '../i18n';

export default function Login() {
  const { t } = useTranslation();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
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
          <p>{t('brand.slogan')}</p>
        </div>
        <form onSubmit={handleSubmit}>
          {error && <div className="alert-error">{error}</div>}
          <div className="form-group">
            <label>{t('auth.login.email')}</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} required autoFocus />
          </div>
          {isRegister && (
            <>
              <div className="form-group">
                <label>{t('auth.register.email')}</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} required />
              </div>
              <div className="form-group">
                <label>{t('auth.register.firstName')}</label>
                <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} required />
              </div>
            </>
          )}
          <div className="form-group">
            <label>{t('auth.login.password')}</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} placeholder={t('auth.password.placeholder') || 'Mindestens 8 Zeichen'} />
            {isRegister && (
              <small className="form-hint">{t('auth.password.requirements') || 'Mindestens 8 Zeichen, 1 Großbuchstabe, 1 Kleinbuchstabe, 1 Zahl'}</small>
            )}
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? `${t('ui.table.loading')}` : (isRegister ? t('auth.register.submit') : t('auth.login.submit'))}
          </button>
        </form>
        <p className="login-toggle">
          <button onClick={() => { setIsRegister(!isRegister); setError(null); }} className="link-btn">
            {isRegister ? t('auth.login.submit') : t('auth.register.title')}
          </button>
        </p>
      </div>
    </div>
  );
}
