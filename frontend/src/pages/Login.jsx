import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register } from '../api';
import { Building2, BarChart3, Shield, Globe } from 'lucide-react';

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
      <div className="login-left">
        <div className="login-branding">
          <h1>Immobilien&shy;verwaltung, einfach digital.</h1>
          <p>
            Verwalten Sie Ihre Immobilien, Mieter und Finanzen an einem Ort.
            Professionell, sicher und effizient.
          </p>
          <div className="login-features">
            <div className="login-feature">
              <div className="login-feature-icon"><Building2 size={18} /></div>
              <span>Portfolio- & Objektverwaltung</span>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon"><BarChart3 size={18} /></div>
              <span>Finanzübersicht & Buchungen</span>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon"><Shield size={18} /></div>
              <span>Sichere Datenverwaltung</span>
            </div>
            <div className="login-feature">
              <div className="login-feature-icon"><Globe size={18} /></div>
              <span>Mehrsprachig (DE, EN, ES)</span>
            </div>
          </div>
        </div>
      </div>

      <div className="login-right">
        <div className="login-card">
          <div className="login-header">
            <h2>ImmoManager <span className="pro">Pro</span></h2>
            <p>{isRegister ? 'Neues Konto erstellen' : 'Willkommen zurück'}</p>
          </div>
          <form onSubmit={handleSubmit}>
            {error && <div className="alert alert-error">{error}</div>}
            <div className="form-group">
              <label>Benutzername</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Ihr Benutzername"
                required
                autoFocus
              />
            </div>
            {isRegister && (
              <>
                <div className="form-group">
                  <label>E-Mail</label>
                  <input
                    type="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="name@beispiel.de"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Vollständiger Name</label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={e => setFullName(e.target.value)}
                    placeholder="Vor- und Nachname"
                    required
                  />
                </div>
              </>
            )}
            <div className="form-group">
              <label>Passwort</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Mindestens 6 Zeichen"
                required
                minLength={6}
              />
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
    </div>
  );
}
