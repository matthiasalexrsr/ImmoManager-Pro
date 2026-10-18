import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { api } from '../../api';
import { assistantApi } from './assistantApi';
import { useModalDialog } from '../partyWorkspace/useModalDialog';

const labels = { disconnected: 'Nicht angemeldet', connecting: 'Anmeldung läuft', connected: 'Angemeldet', unavailable: 'Client fehlt', error: 'Verbindung prüfen' };
function loginHref(value, provider) {
  const hosts = provider === 'codex' ? ['auth.openai.com', 'chatgpt.com'] : provider === 'claude' ? ['claude.ai', 'claude.com', 'console.anthropic.com', 'platform.claude.com', 'accounts.anthropic.com', 'auth.anthropic.com'] : [];
  try { const url = new URL(value); return url.protocol === 'https:' && hosts.includes(url.hostname) && (!url.port || url.port === '443') && !url.username && !url.password && !url.hash ? url.href : ''; } catch { return ''; }
}
function LoginCode({ onComplete, disabled }) {
  const [code, setCode] = useState('');
  return <form onSubmit={event => { event.preventDefault(); const submitted = code.trim(); setCode(''); if (submitted) onComplete(submitted); }}><label>Einmal-Anmeldecode von Claude<input aria-label="Einmal-Anmeldecode" autoComplete="off" spellCheck="false" value={code} disabled={disabled} onChange={event => setCode(event.target.value)} /></label><button className="btn btn-secondary" disabled={disabled || !code.trim()}>Anmeldung bestätigen</button></form>;
}

export default function AssistantAccounts({ state, onClose }) {
  const ref = useRef(null); useModalDialog(ref, onClose);
  const [provider, setProvider] = useState(state.provider === 'local' ? state.capabilities?.providers.find(item => item.id !== 'local')?.id || 'codex' : state.provider);
  const capability = state.capabilities?.providers.find(item => item.id === provider);
  const [connection, setConnection] = useState(capability || {}); const [attempt, setAttempt] = useState(0);
  const alive = useRef(false), selected = useRef(provider), cache = useRef({});
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); const session = api.captureSession();
    setConnection(cache.current[provider] || state.capabilities?.providers.find(item => item.id === provider) || {});
    assistantApi.connection(provider, { signal: controller.signal }).then(value => { session(); if (!controller.signal.aborted && alive.current && selected.current === provider) { cache.current[provider] = value; setConnection(value); } }).catch(failure => { if (!controller.signal.aborted && alive.current && selected.current === provider) setConnection({ status: 'error', reason: failure.message }); });
    return () => controller.abort();
  }, [provider, attempt, state.capabilities]);
  useEffect(() => { if (connection.status !== 'connecting') return; const timer = setTimeout(() => setAttempt(value => value + 1), 2500); return () => clearTimeout(timer); }, [connection]);
  const pending = connection.pending_login;
  const terminal = pending && ['failed', 'cancelled', 'expired', 'completed'].includes(pending.status);
  const href = loginHref(pending?.verification_url || pending?.auth_url, provider);
  const disabled = state.busy || provider === state.provider && ['queued', 'running'].includes(state.run?.state) || Boolean(state.editPending);
  const action = async kind => { const target = provider; const value = await state.connect(kind, target, pending?.id); if (value && alive.current && selected.current === target) { cache.current[target] = value; setConnection(value); setAttempt(previous => previous + 1); } };
  const complete = async code => { const target = provider; const value = await state.completeLogin(code, target, pending?.id); if (value && alive.current && selected.current === target) { cache.current[target] = value; setConnection(value); setAttempt(previous => previous + 1); } };
  return createPortal(<div className="modal-overlay" onMouseDown={event => { if (event.currentTarget === event.target) onClose(); }}><section className="modal assistant-account-dialog" ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Konten und Modelle">
    <header className="modal-header"><div><h2>Konten und Modelle</h2><p>Ihr Konto verbindet den Assistenten. Die Unterhaltungen bleiben in dieser Anwendung.</p></div><button type="button" className="assistant-remove" aria-label="Kontoeinrichtung schließen" onClick={onClose}><X /></button></header>
    <div className="modal-body"><div className="assistant-account-tabs">{(state.capabilities?.providers || []).filter(item => item.id !== 'local').map(item => <button key={item.id} type="button" className="btn btn-secondary" aria-pressed={provider === item.id} disabled={state.busy} onClick={() => { selected.current = item.id; setProvider(item.id); }}>{item.label}</button>)}</div>
      {provider === 'local' ? <p>Wählen Sie ChatGPT oder Claude für freie Fragen und Verwaltungsaufträge. Die lokale Regelprüfung benötigt kein Konto.</p> : <>
        <h3>{capability?.label}</h3><p role="status">{labels[connection.status] || 'Verbindung wird geprüft …'}</p>
        {(connection.reason || capability?.reason) && <p role="status">{connection.reason || capability.reason}</p>}
        {capability?.available && <button type="button" className="btn btn-secondary" disabled={disabled} onClick={() => action('probe')}>Anmeldestatus prüfen</button>}
        {connection.connected ? <><p>{connection.account_access_verified_by_inference ? 'Eine Modellantwort wurde mit diesem Konto erfolgreich verarbeitet.' : 'Anmeldung vorhanden. Eine erfolgreiche Modellantwort wurde für dieses Konto noch nicht bestätigt.'}</p><button type="button" className="btn btn-secondary" disabled={disabled} onClick={() => action('disconnect')}>Kontoverbindung trennen</button></>
          : capability?.available && <div className="assistant-connection">{provider === 'codex' && <p>Für diese Anmeldung die Gerätecode-Anmeldung in den ChatGPT-Sicherheitseinstellungen freigeben. <a href="https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta" target="_blank" rel="noopener noreferrer">Offizielle Anmeldehilfe</a></p>}
            {pending && !terminal ? <><strong>Anmeldung mit Ihrem Konto</strong>{pending.user_code && <p>Anmeldecode: <code>{pending.user_code}</code></p>}{href && <a href={href} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">Anmeldung im Browser öffnen</a>}<p>{pending.error || 'Schließen Sie die Anmeldung beim Anbieter ab. Der Status wird hier aktualisiert.'}</p>{pending.can_submit_code && <LoginCode key={`${provider}:${pending.id}`} disabled={disabled} onComplete={complete} />}<button type="button" className="btn btn-secondary" disabled={disabled} onClick={() => action('cancel')}>Anmeldung abbrechen</button></>
              : <><p>{terminal ? pending.error || 'Der vorige Anmeldeversuch ist beendet.' : 'Die Anmeldung erfolgt direkt beim Anbieter. Diese Anwendung benötigt kein Passwort und keinen API-Schlüssel.'}</p><button type="button" className="btn btn-primary" disabled={disabled} onClick={() => action('login')}>{terminal ? 'Erneut anmelden' : `Mit ${capability.label} anmelden`}</button></>}
          </div>}
        <details><summary>Einrichtungsdetails</summary><p>Kontoclient: {connection.client_available === false || capability?.available === false ? 'Nicht verfügbar' : 'Verfügbar'}</p><p>Modelle: {['verified', 'completed', 'available'].includes(connection.model_discovery_status) ? 'Vom Anbieter ermittelt' : 'Verfügbarkeit wird beim tatsächlichen Einsatz geprüft; Vorgaben sind keine Kontofreigabe.'}</p></details>
      </>}
      {state.error && <p className="assistant-alert error" role="alert">{state.error}</p>}
    </div><footer className="modal-footer"><button type="button" className="btn btn-primary" onClick={onClose}>Zur Unterhaltung</button></footer>
  </section></div>, document.body);
}
