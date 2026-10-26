import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../../api';
import { useAuth, useCanWrite } from '../../contexts/AuthContext';
import { formatMoney } from '../../utils/format';
import { Pill } from '../maintenanceProject/ProjectUi';

export default function PaymentSecurity({ invoiceId }) {
  const location = useLocation();
  const [open, setOpen] = useState(location.hash === '#bankfreigabe');
  return <section className="panel mp-section" id="bankfreigabe">
    <div className="mp-section-body"><h2>Bankdaten und Zahlungsfreigabe</h2>
      <p>Ein Zahlungsvorschlag benötigt einen geprüften Empfänger und eine Freigabe für den aktuellen Rechnungsstand.</p>
      <button type="button" className="btn btn-secondary btn-sm" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? 'Bankdatenprüfung schließen' : 'Bankdatenprüfung öffnen'}</button>
      {open && <PaymentSecurityForm invoiceId={invoiceId} />}
    </div>
  </section>;
}

function PaymentSecurityForm({ invoiceId }) {
  const auth = useAuth();
  const canWrite = useCanWrite(`/invoices/${invoiceId}/payment-authorization`);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [recipient, setRecipient] = useState({ name: '', iban: '', bic: '', reason: '' });
  const [decision, setDecision] = useState({ reason: '', bank_verification: '', totp_code: '' });
  const commands = useRef({});
  const base = `/invoices/${encodeURIComponent(invoiceId)}`;
  useEffect(() => {
    const controller = new AbortController();
    api.get(`${base}/payment-authorization`, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setData(result);
      setRecipient({ name: result.recipient?.name || '', iban: result.recipient?.iban || '', bic: result.recipient?.bic || '', reason: '' });
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [base, reload]);
  const submit = async (event, kind) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    const fields = kind === 'payment-recipient' ? { ...recipient, bic: recipient.bic.trim() || null } :
      { ...decision, totp_code: decision.totp_code || null };
    const fingerprint = JSON.stringify([kind, data.revision, { ...fields, totp_code: undefined }]);
    commands.current[fingerprint] ||= crypto.randomUUID();
    try {
      const result = await api.post(`${base}/${kind}`, { ...fields, expected_revision: data.revision,
        idempotency_key: commands.current[fingerprint] });
      setData(result); setDecision({ reason: '', bank_verification: '', totp_code: '' });
    } catch (failure) { setError(failure.message); setDecision(value => ({ ...value, totp_code: '' })); }
    finally { setBusy(false); }
  };
  const setPayee = (name, value) => setRecipient(current => ({ ...current, [name]: value }));
  const setCheck = (name, value) => setDecision(current => ({ ...current, [name]: value }));
  const self = data?.recipient?.created_by === auth?.user?.id;
  const single = data?.policy.effective_mode === 'single_user';
  return <div>
    {error && <p className="alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setError(null); setReload(value => value + 1); }}>Aktuellen Stand laden</button></p>}
    {!data ? <p role="status">Bankdatenprüfung wird geladen …</p> : <>
      <p><Pill tone={data.authorized ? 'green' : 'orange'}>{data.authorized ? 'Bankdaten freigegeben' : 'Zahlungsvorschlag gesperrt'}</Pill> · {formatMoney(data.amount)}</p>
      <p>{single ? 'Einzelbenutzermodus: erneute TOTP-Prüfung und dokumentierte Gegenprüfung erforderlich.' : 'Vier-Augen-Prüfung: Die Person, die die Bankdaten erfasst hat, gibt sie nicht selbst frei.'}</p>
      {data.policy.inactive_reason && <p>{data.policy.inactive_reason}</p>}
      {!!data.blockers.length && <ul>{data.blockers.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
      {data.recipient && <dl className="ei-facts"><div><dt>Empfänger, Version {data.recipient.number}</dt><dd>{data.recipient.name}</dd></div>
        <div><dt>IBAN / BIC</dt><dd>{data.recipient.iban} · {data.recipient.bic || '—'}</dd></div></dl>}
      {canWrite && <details><summary>{data.recipient ? 'Empfänger ändern (erneute Freigabe erforderlich)' : 'Empfänger erfassen'}</summary>
        <form onSubmit={event => submit(event, 'payment-recipient')}>
          <label className="form-group">Kontoinhaber<input required maxLength={300} value={recipient.name} onChange={event => setPayee('name', event.target.value)} /></label>
          <label className="form-group">IBAN<input required maxLength={42} autoComplete="off" value={recipient.iban} onChange={event => setPayee('iban', event.target.value)} /></label>
          <label className="form-group">BIC (optional)<input maxLength={11} value={recipient.bic} onChange={event => setPayee('bic', event.target.value.toUpperCase())} /></label>
          <label className="form-group">Grund und Quelle der Bankangaben<textarea required minLength={10} maxLength={2000} value={recipient.reason} onChange={event => setPayee('reason', event.target.value)} /></label>
          <button className="btn btn-secondary" disabled={busy}>Neue Empfängerversion speichern</button>
        </form>
      </details>}
      {canWrite && !data.authorized && data.recipient && data.eligible && <form onSubmit={event => submit(event, 'payment-authorization')}>
        <h3>Bankverbindung gegenprüfen</h3>
        {self && !single && <p className="alert-error">Diese Empfängerversion wurde von Ihnen erfasst. Eine andere berechtigte Person muss sie freigeben.</p>}
        <label className="form-group">Dokumentierte Gegenprüfung<textarea required minLength={20} maxLength={2000} value={decision.bank_verification}
          placeholder="Zum Beispiel: Rückruf über eine bereits bekannte Kontaktnummer, Datum und Ergebnis."
          onChange={event => setCheck('bank_verification', event.target.value)} /></label>
        <label className="form-group">Freigabebegründung<textarea required minLength={10} maxLength={2000} value={decision.reason} onChange={event => setCheck('reason', event.target.value)} /></label>
        {single && <label className="form-group">Neuer Zwei-Faktor-Code<input required type="password" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6}
          value={decision.totp_code} onChange={event => setCheck('totp_code', event.target.value)} /></label>}
        <button className="btn btn-primary" disabled={busy || (self && !single)}>Diesen Betrag und Empfänger freigeben</button>
      </form>}
      {data.authorized && <p role="status">Die Freigabe gilt für den angezeigten Betrag und Datensatzstand. Relevante Änderungen erfordern eine neue Entscheidung.</p>}
      {!!data.authorization_history.length && <details><summary>Freigabenachweise ({data.authorization_history.length})</summary><ul>{data.authorization_history.map(row => <li key={row.id}>
        {formatMoney(row.amount)} · {row.mode === 'single_user' ? 'Einzelbenutzer mit TOTP' : 'Vier-Augen-Prüfung'}<p>{row.reason}</p><p>{row.verification}</p>
        {row.id !== data.authorization?.id && <strong>Gilt nicht für den aktuellen Stand.</strong>}
      </li>)}</ul></details>}
    </>}
  </div>;
}

export function BankModeSettings() {
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  return <section className="mp-section-body"><h3>Bankdatenfreigabe</h3><p>Standard: Vier-Augen-Prüfung unabhängig von Betragsgrenzen der Rechnungsprüfung.</p>
    {auth?.user?.role === 'eigentuemer' && <><button className="btn btn-secondary btn-sm" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>Einzelbenutzermodus verwalten</button>
      {open && <BankModeForm />}</>}
  </section>;
}

function BankModeForm() {
  const commands = useRef({});
  const [data, setData] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [reason, setReason] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api.get('/payment-security/settings', { signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) { setData(result); setEnabled(result.single_user_mode); }
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, []);
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(null);
    const fingerprint = JSON.stringify([data.revision, enabled, reason]);
    commands.current[fingerprint] ||= crypto.randomUUID();
    try {
      setData(await api.put('/payment-security/settings', { expected_revision: data.revision,
        idempotency_key: commands.current[fingerprint], single_user_mode: enabled, reason, totp_code: code || null }));
      setCode(''); setReason('');
    } catch (failure) { setError(failure.message); setCode(''); }
    finally { setBusy(false); }
  };
  return <form onSubmit={submit}>
    {error && <p className="alert-error" role="alert">{error}</p>}
    {!data ? <p role="status">Sicherheitsmodus wird geladen …</p> : <>
      <p role="status">Aktiv: {data.effective_mode === 'single_user' ? 'Einzelbenutzermodus' : 'Vier-Augen-Prüfung'}</p>
      <label><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} /> Einzelbenutzermodus ausdrücklich aktivieren</label>
      <p>Nur bei genau einem aktiven Finanzbenutzer. Jede Bankdatenfreigabe verlangt weiterhin eine Gegenprüfung, Begründung und einen neuen TOTP-Code.</p>
      <label className="form-group">Begründung der Einstellung<textarea required minLength={20} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      {enabled && <label className="form-group">Neuer Zwei-Faktor-Code<input type="password" required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={event => setCode(event.target.value)} /></label>}
      <button className="btn btn-primary" disabled={busy}>Sicherheitsmodus speichern</button>
    </>}
  </form>;
}
