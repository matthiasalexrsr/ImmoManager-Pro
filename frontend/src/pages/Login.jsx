import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register } from '../api';

export default function Login() {
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
          <p>Immobilienverwaltung</p>
        </div>
        <form onSubmit={handleSubmit}>
          {error && <div className="alert-error">{error}</div>}
          <div className="form-group">
            <label>Benutzername</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} required autoFocus placeholder="Ihr Benutzername" />
          </div>
          {isRegister && (
            <>
              <div className="form-group">
                <label>E-Mail</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="name@firma.de" />
              </div>
              <div className="form-group">
                <label>Vollständiger Name</label>
                <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} required placeholder="Max Mustermann" />
              </div>
            </>
          )}
          <div className="form-group">
            <label>Passwort</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={8} placeholder="Mindestens 8 Zeichen" />
            {isRegister && (
              <small className="form-hint">Mindestens 8 Zeichen mit Buchstaben und Zahlen</small>
            )}
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? 'Bitte warten...' : (isRegister ? 'Registrieren & Anmelden' : 'Anmelden')}
          </button>
        </form>
        <p className="login-toggle">
          {isRegister ? 'Bereits registriert?' : 'Noch kein Konto?'}{' '}
          <button onClick={() => { setIsRegister(!isRegister); setError(null); }} className="link-btn">
            {isRegister ? 'Anmelden' : 'Registrieren'}
          </button>
        </p>
      </div>
    </div>
  );
}
