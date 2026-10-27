import { useEffect, useState } from 'react';
import { api } from '../api';
import { formatMoney } from '../utils/format';
import { Link } from 'react-router-dom';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { financeCommandKey, forgetFinanceCommand, readFinanceCommand, rememberFinanceCommand } from './financeCommandBuffer';

export default function ReceivableSettlement({ receivable, onChanged }) {
  const canEdit = useCanWrite('/receivables');
  const canBook = useCanWrite('/bookings');
  const owner = useAuth()?.user?.id;
  const commandKey = financeCommandKey(owner, receivable.id);
  const [pendingState, setPending] = useState(() => ({ key: commandKey, command: readFinanceCommand(commandKey) }));
  const pending = pendingState.key === commandKey ? pendingState.command : readFinanceCommand(commandKey);
  const [state, setState] = useState(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [sources, setSources] = useState([]);
  const [source, setSource] = useState('');
  const [amount, setAmount] = useState('');
  const [day, setDay] = useState(new Date().toLocaleDateString('sv-SE'));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [revision, setRevision] = useState(0);
  const [asOf, setAsOf] = useState(new Date().toLocaleDateString('sv-SE'));
  useEffect(() => {
    const changed = event => { if (event.key === commandKey) setPending({ key: commandKey, command: readFinanceCommand(commandKey) }); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [commandKey]);
  useEffect(() => {
    const controller = new AbortController();
    const current = api.captureSession();
    api.get(`/receivables/${receivable.id}/residual?as_of=${encodeURIComponent(asOf)}`, { signal: controller.signal }).then(value => { current(); setState(value); })
      .catch(e => { if (!controller.signal.aborted) { setState(null); setError(e.message); } });
    return () => controller.abort();
  }, [receivable.id, receivable.updated_at, revision, asOf]);
  const show = async () => {
    const current = api.captureSession(); setOpen(true); setError('');
    try {
      const contract = await api.get(`/contracts/${receivable.contract_id}`); current();
      const [bookings, credits] = await Promise.all([api.list(`/bookings?tenant_id=${contract.tenant_id}`), api.list(`/receivables?contract_id=${contract.id}`)]); current();
      setSources([...bookings.filter(b => Number(b.amount) > 0 && !b.reverses_booking_id).map(b => ({ value: `booking:${b.id}`, label: `${b.booking_date} · ${formatMoney(b.amount)} · ${b.payment_text || 'Zahlung'}` })),
        ...credits.filter(c => Number(c.amount_due) < 0).map(c => ({ value: `credit:${c.id}`, label: `Guthaben ${c.due_date} · ${formatMoney(-c.amount_due)}` }))]);
    } catch (e) { setError(e.message); }
  };
  const execute = async wanted => {
    if (!owner) { setError('Die Anmeldung wird noch geprüft. Bitte erneut versuchen.'); return; }
    const current = api.captureSession(); setBusy(true); setError('');
    const command = pending || wanted;
    try {
      rememberFinanceCommand(commandKey, command);
      setPending({ key: commandKey, command });
      await api.post(command.path, command.request); current();
      forgetFinanceCommand(commandKey, command); setPending({ key: commandKey, command: null });
      setRevision(r => r + 1); setOpen(false); setKey(crypto.randomUUID());
      onChanged?.();
    } catch (e) {
      try { current(); } catch { return; }
      if (e.statusCode === 409 || e.statusCode === 422) { forgetFinanceCommand(commandKey, command); setPending({ key: commandKey, command: null }); }
      setError(e.message);
    } finally { try { current(); setBusy(false); } catch { /* A departed session cannot update this page. */ } }
  };
  const submit = async e => {
    e.preventDefault();
    const [kind, id] = source.split(':');
    await execute({ path: `/receivables/${receivable.id}/settlements`, request: { expected_revision: state.revision, idempotency_key: key,
      [kind === 'booking' ? 'booking_id' : 'credit_id']: id, amount, effective_date: day, reason } });
  };
  const edited = setter => e => { setter(e.target.value); setKey(crypto.randomUUID()); };
  const undo = id => execute({ path: `/receivables/${receivable.id}/settlements/${id}/reverse`, request: { expected_revision: state.revision,
    idempotency_key: key, effective_date: day, reason } });
  const cash = value => formatMoney(value, { currency: state?.currency || 'EUR' });
  const legacy = state && (state.unresolved_legacy || state.undated_legacy_closed)
    ? 'Altbestand ohne vollständigen datierten Zahlungsnachweis' : '';
  // in the list: the amount (a legacy claim marked, the whole sentence on hover and when opened), its button beneath
  return <div className="receivable-settlement">{state ? <><span className="receivable-settlement__line"><strong>{cash(state.residual)}</strong>
    {legacy && <span className="badge badge-gray" title={legacy}>Altbestand</span>}</span>
    <button type="button" className="btn btn-sm btn-secondary" onClick={show}>Rest / Ausgleich</button></>
    : <span>Rest wird geladen …</span>}
    {state && pending && <p role="status">Ein Ausgleich wartet auf Bestätigung. Eingaben bleiben bis zur Klärung gesperrt.
      <button type="button" disabled={busy || !canEdit || !canBook} onClick={() => execute(pending)}>Ausgleich prüfen und fortsetzen</button></p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => setRevision(r => r + 1)}>Stand neu laden</button></p>}
    {open && <div className="receivable-settlement__panel"><button type="button" className="btn btn-sm btn-secondary" onClick={() => setOpen(false)}>Schließen</button>
      {legacy && <p>{legacy}</p>}
      <label>Rest zum <input type="date" required value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
      <ul>{state?.evidence.map((e, i) => <li key={i}>{e.date}: {cash(e.amount)} ({e.kind === 'deposit' ? 'Kaution' : e.kind === 'reversal' ? 'Storno' : e.kind === 'allocation_reversal' ? 'Rücknahme' : e.kind === 'credit' ? 'Guthaben' : 'Zahlung'}) {e.url && <Link to={e.url}>Quelle öffnen</Link>}</li>)}</ul>
      {canEdit && canBook && state?.allocations?.length > 0 && <fieldset><legend>Zuordnung begründet zurücknehmen</legend>
        <label>Rücknahme am <input type="date" value={day} onChange={edited(setDay)} /></label>
        <label>Grund der Rücknahme <input minLength={3} value={reason} onChange={edited(setReason)} /></label>
        {state.allocations.filter(a => !a.reverses_id && !state.allocations.some(r => r.reverses_id === a.id)).map(a => <div key={a.id}>
          {a.effective_date}: {cash(a.amount)} · {a.reason} <button type="button" disabled={busy || Boolean(pending) || reason.trim().length < 3 || !day} onClick={() => undo(a.id)}>Diese Zuordnung zurücknehmen</button>
        </div>)}
      </fieldset>}
      {canEdit && canBook && state && !state.unresolved_legacy && !state.undated_legacy_closed && Number(state.residual) > 0 && <form onSubmit={submit}>
        <label>Zahlung oder Guthaben <select disabled={busy || Boolean(pending)} required value={source} onChange={edited(setSource)}><option value="">Bitte auswählen</option>{sources.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}</select></label>
        <label>Teilbetrag (€) <input disabled={busy || Boolean(pending)} required type="number" min="0.01" step="0.01" value={amount} onChange={edited(setAmount)} /></label>
        <label>Ausgleich am <input disabled={busy || Boolean(pending)} required type="date" value={day} onChange={edited(setDay)} /></label>
        <label>Begründung <input disabled={busy || Boolean(pending)} required minLength={3} value={reason} onChange={edited(setReason)} /></label>
        <button type="submit" disabled={busy}>{busy ? 'Wird gespeichert …' : 'Belegt zuordnen'}</button>
      </form>}
    </div>}
  </div>;
}
