import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';

export default function SecuritySection() {
  const auth = useAuth();
  const [enabled, setEnabled] = useState(null);
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sessionInvalid, setSessionInvalid] = useState(false);
  const operation = useRef(0);
  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const same = api.captureSession();
        const data = await api.get('/auth/2fa/status'); same(); if (live) setEnabled(data.enabled);
      } catch (failure) {
        if (!live) return;
        if (failure.code === 'SESSION_CHANGED') { setSessionInvalid(true); setEnabled(null); setSetup(null); setCode(''); }
        else setError(failure.message);
      }
    }
    load();
    return () => { live = false; operation.current += 1; };
  }, [auth?.user?.id]);
  const run = async action => {
    if (busy || sessionInvalid) return;
    const current = ++operation.current; setBusy(true); setError(null);
    try {
      const same = api.captureSession();
      const data = await api.post(`/auth/2fa/${action}`, action === 'setup' ? {} : { code });
      same(); if (operation.current !== current) return;
      if (action === 'setup') setSetup(data);
      else { setEnabled(data.enabled); setSetup(null); setCode(''); }
    } catch (failure) {
      if (operation.current !== current) return;
      if (failure.code === 'SESSION_CHANGED') { setSessionInvalid(true); setEnabled(null); setSetup(null); setCode(''); }
      else setError(failure.message);
    }
    finally { if (operation.current === current) setBusy(false); }
  };
  if (sessionInvalid) return <section className="panel security-settings"><p role="alert">Die Sitzung wurde geändert. Bitte erneut anmelden.</p></section>;
  return <section className="panel security-settings"><div className="panel-header">Sicherheit und Zwei-Faktor-Anmeldung</div><div className="panel-body settings-section">
    <p>Angemeldet als {auth?.user?.full_name || auth?.user?.username}. {enabled === null ? 'Status wird geprüft …' : enabled ? 'Zwei-Faktor-Anmeldung ist aktiviert.' : 'Zwei-Faktor-Anmeldung ist nicht aktiviert.'}</p>
    {error && <p role="alert">{error}</p>}
    {!enabled && enabled !== null && !setup && <button className="btn btn-secondary" disabled={busy} onClick={() => run('setup')}>Authenticator einrichten</button>}
    {setup && <><p>Den folgenden Schlüssel in Ihrer Authenticator-App eintragen. Er wird nur für diese Einrichtung angezeigt.</p><code style={{ overflowWrap: 'anywhere' }}>{setup.secret}</code></>}
    {(setup || enabled) && <><label htmlFor="totp-code">Aktueller sechsstelliger Code</label><input id="totp-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e => setCode(e.target.value)} />
      <button className="btn btn-secondary" disabled={busy || !/^\d{6}$/.test(code)} onClick={() => run(enabled ? 'disable' : 'verify')}>{enabled ? 'Mit Code deaktivieren' : 'Einrichtung bestätigen'}</button></>}
  </div></section>;
}
