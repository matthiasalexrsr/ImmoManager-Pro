import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import { useAuth, useCanWrite } from '../contexts/AuthContext';
import { useDataStore } from '../contexts/DataStoreContext';
import { formatDate, formatMoney, formatMonth } from '../utils/format';
import RentPaymentDialog from '../features/rentPayments/RentPaymentDialog';
import './rentOverview.css';

const localDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};
const amountKeys = ['expected', 'paid', 'outstanding', 'contract_credit'];
const validLedger = data => data && Array.isArray(data.rows) && data.totals
  && amountKeys.every(key => Number.isFinite(data.totals[key]))
  && data.rows.every(row => row.contract_id && row.contract_revision && amountKeys.every(key => Number.isFinite(row[key])));

function readPending(key) {
  if (!key) return null;
  try {
    const value = JSON.parse(sessionStorage.getItem(key));
    return value?.request?.idempotency_key && value?.request?.contract_id === value?.row?.contract_id ? value : null;
  } catch { return null; }
}

function clearPending(key, command) {
  if (readPending(key)?.request.idempotency_key === command.request.idempotency_key) sessionStorage.removeItem(key);
}

export default function RentOverview() {
  const auth = useAuth();
  const store = useDataStore();
  const canWrite = useCanWrite('/bookings');
  const pendingKey = auth?.user?.id ? `immo:pending-rent-payment:${auth.user.id}` : null;
  const [today] = useState(localDate);
  const [filters, setFilters] = useState({ month: today.slice(0, 7), as_of: today, property_id: '' });
  const [ledger, setLedger] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [choices, setChoices] = useState({ accounts: [], properties: [] });
  const [choiceError, setChoiceError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [paymentRow, setPaymentRow] = useState(null);
  const [pending, setPending] = useState(() => readPending(pendingKey));
  const [receipt, setReceipt] = useState(null);
  const pendingRef = useRef(pending);
  const generationRef = useRef(0);

  useEffect(() => {
    generationRef.current += 1;
    const recovered = readPending(pendingKey);
    pendingRef.current = recovered;
    setPending(recovered);
    setPaymentRow(null);
    setReceipt(null);
    return () => { generationRef.current += 1; };
  }, [pendingKey]);

  useEffect(() => {
    const controller = new AbortController();
    setChoiceError(null);
    Promise.all(['/accounts', '/properties'].map(path => api.list(path, { signal: controller.signal })))
      .then(([accounts, properties]) => {
        if (!Array.isArray(accounts) || !Array.isArray(properties)) throw new Error('Konten und Immobilien konnten nicht geladen werden.');
        if (!controller.signal.aborted) setChoices({ accounts, properties });
      }).catch(failure => { if (!controller.signal.aborted) setChoiceError(failure.message); });
    return () => controller.abort();
  }, [revision, pendingKey]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setLedger(null);
    if (!filters.month || !filters.as_of) {
      setError('Bitte Mietmonat und Stichtag vollständig angeben.');
      setLoading(false);
      return () => controller.abort();
    }
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    api.get(`/rent-charges/ledger?${query}`, { signal: controller.signal }).then(data => {
      if (!validLedger(data)) throw new Error('Die Mietübersicht enthält keine gültigen Beträge.');
      if (!controller.signal.aborted) setLedger(data);
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, revision, pendingKey]);

  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const save = async values => {
    const generation = generationRef.current;
    let command = pendingRef.current;
    if (!command) {
      if (!pendingKey) throw new Error('Die Anmeldung wird noch geprüft. Bitte erneut versuchen.');
      command = { row: paymentRow, request: { ...values, amount: String(values.amount),
        contract_id: paymentRow.contract_id, contract_revision: paymentRow.contract_revision,
        idempotency_key: crypto.randomUUID() } };
      // Persist before sending, so a lost response can resume this exact command after navigation.
      sessionStorage.setItem(pendingKey, JSON.stringify(command));
      pendingRef.current = command;
      setPending(command);
    }
    const current = () => generationRef.current === generation
      && pendingRef.current?.request.idempotency_key === command.request.idempotency_key;
    let result;
    try {
      result = await api.post('/rent-charges/contract-payment', command.request);
      if (!result?.booking?.id || result.contract_id !== command.request.contract_id) {
        throw new Error('Die Serverantwort bestätigt die Buchung nicht. Bitte denselben Vorgang erneut prüfen.');
      }
    } catch (failure) {
      if (!current()) return;
      // These validation responses precede every write. Unknown outcomes retain the command.
      if ([400, 422].includes(failure.statusCode) || ['RENT_PAYMENT_NOT_CREATED', 'RENT_PAYMENT_REMOVED', 'RENT_PAYMENT_CHANGED', 'RENT_PAYMENT_RECORDED_UNAVAILABLE'].includes(failure.code)) {
        clearPending(pendingKey, command);
        pendingRef.current = null;
        setPending(null);
      }
      throw failure;
    }
    if (!current()) return;
    clearPending(pendingKey, command);
    pendingRef.current = null;
    setPending(null);
    setPaymentRow(null);
    setReceipt(result);
    store?.invalidateRelated('bookings', 'accounts', 'contracts', 'rent_charges', 'tenants');
    refresh();
  };

  const columns = [
    { key: 'contract_number', label: 'Vertrag', filterType: 'text' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text', render: (value, row) => <PartyLink tenantId={row.tenant_id}>{value}</PartyLink> },
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text' },
    { key: 'expected', label: 'Vereinbarte Miete', type: 'currency' },
    { key: 'paid', label: 'Aus Zahlungen gedeckt', type: 'currency' },
    { key: 'outstanding', label: 'Offen', type: 'currency' },
    { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
    { key: 'payment', label: 'Zahlung', render: (_, row) => canWrite && pendingKey
      ? <button type="button" className="btn btn-sm btn-secondary" disabled={Boolean(pending) || Boolean(choiceError)}
        onClick={() => setPaymentRow(row)}>Eingang buchen</button>
      : <Link to={`/tenants/${encodeURIComponent(row.tenant_id)}/account`}>Mieterkonto</Link> },
  ];

  return <div className="page rent-overview">
    <div className="rent-overview-heading"><div><h1>Mietübersicht</h1>
      <p className="text-muted">Vereinbarte Mieten und tatsächlich gebuchte Zahlungen.</p></div>
      <button type="button" className="btn btn-secondary" onClick={refresh}>Aktualisieren</button></div>
    <div className="rent-overview-filters" role="group" aria-label="Mietübersicht filtern">
      <label>Mietmonat<input type="month" value={filters.month} max={filters.as_of.slice(0, 7)}
        onChange={e => setFilters(current => ({ ...current, month: e.target.value }))} /></label>
      <label>Zahlungen bis Stichtag<input type="date" value={filters.as_of} max={today}
        onChange={e => setFilters(current => ({ ...current, as_of: e.target.value }))} /></label>
      <label>Immobilie<select value={filters.property_id} onChange={e => setFilters(current => ({ ...current, property_id: e.target.value }))}>
        <option value="">Alle Immobilien</option>{choices.properties.map(property => <option key={property.id} value={property.id}>{property.name}</option>)}
      </select></label>
    </div>
    {pending && <div className="alert alert-warning" role="status">Ein Zahlungseingang wartet auf Bestätigung.
      <button type="button" className="btn btn-secondary" onClick={() => setPaymentRow(pending.row)}>Buchung fortsetzen</button></div>}
    {receipt && <div className="alert alert-success" role="status">
      {receipt.replayed ? 'Bereits gebuchte Zahlung gefunden.' : 'Zahlung und Vertragszuordnung gespeichert.'} {' '}
      {formatMoney(receipt.booking.amount)} · {formatDate(receipt.booking.booking_date)} {' '}
      <Link to={`/bookings?booking_id=${encodeURIComponent(receipt.booking.id)}`}>Buchung ansehen</Link></div>}
    {choiceError && <div className="alert alert-error" role="alert">Konten / Immobilien: {choiceError} <button type="button" onClick={refresh}>Erneut laden</button></div>}
    {error && <div className="alert alert-error" role="alert">{error} <button type="button" onClick={refresh}>Erneut laden</button></div>}
    {loading && <p role="status">Mieten und Zahlungseingänge werden geladen…</p>}
    {ledger && <>
      <p className="rent-overview-period"><strong>{formatMonth(ledger.month)}</strong> · Zahlungsstand {formatDate(ledger.as_of)}</p>
      <div className={`stats-grid${amountKeys.some(key => formatMoney(ledger.totals[key]).length > 16) ? ' rent-summary-long-values' : ''}`}>
        {[['expected', 'Vereinbarte Miete'], ['paid', 'Aus Zahlungen gedeckt'], ['outstanding', 'Offen im Mietmonat'], ['contract_credit', 'Guthaben der angezeigten Verträge']]
          .map(([key, label]) => <div className="stat-card" key={key}><div className="stat-label">{label}</div>
            <div className="stat-value">{formatMoney(ledger.totals[key])}</div></div>)}
      </div>
      <details className="rent-overview-basis"><summary>So werden Mieten und Zahlungen berechnet</summary>
        <p>Grundlage ist der datierte Mietverlauf einschließlich Teilmonaten. Gebuchte Zahlungen werden ab ihrem Eingangsdatum
          berücksichtigt und decken zuerst ältere Mietmonate. Stornos und Kautionsanteile sind berücksichtigt; Guthaben gilt zum Stichtag.</p>
      </details>
      <DataTable title="Mieten im ausgewählten Monat" columns={columns} data={ledger.rows} />
    </>}
    <nav className="rent-overview-links" aria-label="Weitere Mietvorgänge">
      <Link to="/bookings">Vorhandene Zahlung zuordnen</Link><Link to="/receivables">Weitere Forderungen und Guthaben</Link>
      <Link to="/dunning">Mahnvorgänge</Link><Link to="/rent-charges">Manuell gepflegte Sollstellungen</Link>
    </nav>
    <p className="text-muted">Manuell gepflegte Sollstellungen und weitere Forderungen werden hier nicht zur Vertragsmiete addiert.
      Ihre bisherigen Angaben bleiben in den jeweiligen Listen erhalten. Der Mahnstand kann zusätzliche Forderungen berücksichtigen.</p>
    {paymentRow && <RentPaymentDialog key={paymentRow.contract_id} row={paymentRow}
      accounts={choices.accounts} pending={pending} onSubmit={save} onClose={() => setPaymentRow(null)}
      onReload={() => { setPaymentRow(null); refresh(); }} today={today} />}
  </div>;
}
