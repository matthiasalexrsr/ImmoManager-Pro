import { Fragment, useEffect, useState, useRef } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../components/Toast';
import { formatDate as day, formatMoney } from '../utils/format';
import { PartyLink, usePartyWorkspace } from '../features/partyWorkspace/PartyWorkspace';
import RelatedPageLinks from '../components/RelatedPageLinks';
import { entityHref } from '../utils/entityLinks';
import FormModal from '../components/FormModal';
import { useCanWrite } from '../contexts/AuthContext';
import { PAYMENT_METHODS, TENANT_FIELDS } from '../features/tenants/tenantFields';
import { useDataStore } from '../contexts/DataStoreContext';

const eur = v => formatMoney(v || 0);

/** Per contract what was due, what was paid and the balance, plus payments not credited to any contract. */
export default function TenantAccount() {
  const { id } = useParams();
  return <TenantAccountSession key={id} id={id} />;
}

function TenantAccountSession({ id }) {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const store = useDataStore();
  const party = usePartyWorkspace();
  const canWrite = useCanWrite('/tenants');
  const canSettle = useCanWrite('/receivables');
  const [settling, setSettling] = useState(null);
  const [editing, setEditing] = useState(false);
  const [tenant, setTenant] = useState(null);
  const [account, setAccount] = useState(null);
  const [today] = useState(() => { const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  });
  const asOf = params.get('as_of') ?? today;
  const setAsOf = value => { setEditing(false); setParams(current => {
    const next = new URLSearchParams(current); next.set('as_of', value); return next;
  }); };
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const contractSources = useRef(null);
  const unassignedSources = useRef(null);
  const showSources = target => { target.current?.focus(); target.current?.scrollIntoView?.({ block: 'center' }); };
  const bookingParams = new URLSearchParams({ tenant_id: id, date_to: asOf });
  const bookingHref = `/bookings?${bookingParams}`;
  const unassignedHref = `/bookings?${new URLSearchParams({ ...Object.fromEntries(bookingParams), flow: 'unassigned' })}`;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setAccount(null); setTenant(null); setError(null);
    if (!asOf) { setError('Bitte einen gültigen Stichtag wählen.'); return; }
    Promise.all([
      api.get(`/tenants/${encodeURIComponent(id)}`, options),
      api.get(`/tenants/${encodeURIComponent(id)}/account?as_of=${encodeURIComponent(asOf)}`, options),
    ]).then(([person, result]) => {
      if (!cancelled) { setTenant(person); setAccount(result); }
    }).catch(err => { if (!cancelled) { setError(err.message); toast.error(err.message); } });
    return () => { cancelled = true; controller.abort(); };
  }, [id, asOf, revision]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}</div><input aria-label="Stichtag" type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /><button className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>;

  if (!account) return <div className="page-loading">Lade Mieterkonto...</div>;

  // The server adds the totals in exact cents; adding the rounded rows here in floating point
  // could turn a settled account into "Offen 0,00 €". Older servers send no totals.
  const totals = account.totals ?? account.contracts.reduce((s, c) => ({
    expected: s.expected + c.expected, paid: s.paid + c.paid,
    balance: s.balance + c.outstanding - c.overpaid,
  }), { expected: 0, paid: 0, balance: 0 });
  const unassigned = account.totals?.unassigned ?? account.unassigned.reduce((s, b) => s + b.unassigned, 0);
  // R12-20: the stored claims (back payments, credits, fees) belong to the same account; older servers send none
  const claimsKnown = account.totals?.total_balance != null;
  const suggestions = account.settlement_suggestions ?? [];
  const settle = async proposal => {
    setSettling(proposal.receivable_id);
    try {
      await api.post(`/receivables/${encodeURIComponent(proposal.receivable_id)}/settlements`, {
        expected_revision: proposal.expected_revision, idempotency_key: crypto.randomUUID(),
        booking_id: proposal.booking_id, amount: proposal.amount, effective_date: today < proposal.booking_date ? proposal.booking_date : today,
        reason: 'Ausgleich aus dem Mietguthaben (§ 366 BGB), vorgeschlagen im Mieterkonto' });
      toast.success('Ausgleich gebucht');
      if (store) store.invalidateRelated('receivables', 'bookings');
      setRevision(value => value + 1);
    } catch (err) {
      toast.error(err.message || 'Der Ausgleich ließ sich nicht buchen.');
    } finally {
      setSettling(null);
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Mieterkonto <PartyLink tenantId={id}>{tenant?.full_name || ''}</PartyLink></h1>
      <div className="toolbar">
        <label htmlFor="as-of">Stichtag</label>
        <input id="as-of" type="date" value={asOf} onChange={e => setAsOf(e.target.value)} />
        {canWrite && tenant && <button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing(true)}>Mieter bearbeiten</button>}
        <Link to="/tenants" className="btn btn-sm btn-secondary">Zurück zu den Mietern</Link>
        {party && <button className="btn btn-sm btn-secondary" onClick={() => party.openParty(id, { tab: 'documents' })}>Dokumente der Partei</button>}
      </div>

      <RelatedPageLinks items={[
        { to: `/contracts?tenant_id=${encodeURIComponent(id)}`, label: 'Verträge dieses Mieters' },
        { to: bookingHref, label: 'Buchungen dieses Mieters' },
        { to: `/receivables?${new URLSearchParams({ tenant_id: id, date_to: asOf })}`, label: 'Forderungen und Guthaben' },
      ]} />
      {tenant && <TenantFacts tenant={tenant} />}

      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <button type="button" className="stat-card kpi-action" onClick={() => showSources(contractSources)}><div className="stat-label">Soll</div><div className="stat-value">{eur(totals.expected)}</div></button>
        <button type="button" className="stat-card kpi-action" onClick={() => showSources(contractSources)}><div className="stat-label">Gezahlt (zugeordnet)</div><div className="stat-value">{eur(totals.paid)}</div></button>
        <button type="button" className="stat-card kpi-action" onClick={() => showSources(contractSources)}>
          <div className="stat-label">{totals.balance >= 0 ? 'Offen' : 'Guthaben'}</div>
          <div className={`stat-value ${totals.balance > 0 ? 'text-red' : 'text-green'}`}>{eur(Math.abs(totals.balance))}</div>
        </button>
        <button type="button" className="stat-card kpi-action" onClick={() => showSources(unassignedSources)}><div className="stat-label">Nicht zugeordnet</div><div className="stat-value">{eur(unassigned)}</div></button>
        {claimsKnown && (account.totals.claims || account.totals.credits) ? (
          <button type="button" className="stat-card kpi-action" onClick={() => showSources(contractSources)}>
            <div className="stat-label">{account.totals.total_balance >= 0 ? 'Gesamt offen (mit Forderungen)' : 'Gesamtguthaben (mit Forderungen)'}</div>
            <div className={`stat-value ${account.totals.total_balance > 0 ? 'text-red' : 'text-green'}`}>{eur(Math.abs(account.totals.total_balance))}</div>
          </button>) : null}
      </div>

      {suggestions.length > 0 && (
        <section className="card" aria-label="Vorschläge zum Ausgleich" style={{ marginBottom: '1rem' }}>
          <div className="card-header"><strong>Ausgleich vorschlagen</strong></div>
          <p className="text-muted" style={{ padding: '0 1rem' }}>
            Eine Zahlung wurde als Miete gutgeschrieben, obwohl eine Forderung offen ist. Mit dem Ausgleich wird sie der Forderung zugeordnet; das Mietguthaben sinkt entsprechend.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Vertrag</th><th>Forderung</th><th>Fällig</th><th className="text-right">Offen</th><th>Zahlung</th><th className="text-right">Ausgleich</th><th><span className="sr-only">Aktion</span></th></tr></thead>
              <tbody>
                {suggestions.map(s => (
                  <tr key={`${s.receivable_id}:${s.booking_id}`}>
                    <td>{s.contract_number}</td>
                    <td className="td-wrap">{s.description || 'Forderung'}</td>
                    <td>{day(s.due_date)}</td>
                    <td className="text-right td-num">{eur(s.open)}</td>
                    <td><Link to={entityHref('booking', s.booking_id)}>{day(s.booking_date)}</Link></td>
                    <td className="text-right td-num">{eur(s.amount)}</td>
                    <td>{canSettle && <button type="button" className="btn btn-sm btn-primary" disabled={settling !== null}
                      onClick={() => settle(s)}>Ausgleich buchen</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section ref={contractSources} aria-label="Vertragsquellen zum Stichtag" tabIndex={-1} className="card" style={{ marginBottom: '1rem' }}>
        <div className="card-header"><strong>Verträge</strong></div>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Vertrag</th><th className="text-right">Soll</th><th className="text-right">Gezahlt</th><th className="text-right">Offen</th><th className="text-right">Überzahlt</th>
              {claimsKnown && <><th className="text-right">Forderungen</th><th className="text-right">Gesamtsaldo</th></>}</tr></thead>
            <tbody>
              {account.contracts.map(c => (
                <tr key={c.contract_id}>
                  <td>{c.contract_id && c.contract_number
                    ? <Link to={entityHref('contract', c.contract_id)}>{c.contract_number}</Link>
                    : c.contract_number || '—'}
                    {c.contract_id && <div className="td-sub"><Link to={`/receivables?${new URLSearchParams({ contract_id: c.contract_id, date_to: asOf })}`}>Forderungen & Guthaben</Link></div>}
                    {c.ledger_start && <div className="td-sub">Konto ab {day(c.ledger_start)} übernommen
                      {c.carried_balance ? ` · Saldo ${eur(c.carried_balance)}` : ''}</div>}</td>
                  <td className="text-right td-num">{eur(c.expected)}</td>
                  <td className="text-right td-num">{eur(c.paid)}</td>
                  <td className={`text-right td-num ${c.outstanding > 0 ? 'text-red' : ''}`}>{eur(c.outstanding)}</td>
                  <td className={`text-right td-num ${c.overpaid > 0 ? 'text-green' : ''}`}>{eur(c.overpaid)}</td>
                  {claimsKnown && <>
                    <td className="text-right td-num">{eur((c.claims || 0) - (c.credits || 0))}</td>
                    <td className={`text-right td-num ${c.total_balance > 0 ? 'text-red' : c.total_balance < 0 ? 'text-green' : ''}`}>{eur(c.total_balance)}</td>
                  </>}
                </tr>
              ))}
              {account.contracts.length === 0 && <tr><td colSpan={claimsKnown ? 7 : 5} className="table-empty">Keine Verträge</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section ref={unassignedSources} aria-label="Nicht zugeordnete Zahlungsquellen zum Stichtag" tabIndex={-1} className="card">
        <div className="card-header"><strong>Nicht zugeordnete Zahlungen</strong></div>
        {account.unassigned.length === 0
          ? <p className="text-muted" style={{ padding: '1rem' }}>Alle Zahlungen sind Verträgen zugeordnet.</p>
          : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Datum</th><th>Buchungstext</th><th className="text-right">Betrag</th><th className="text-right">Davon ohne Vertrag</th></tr></thead>
                <tbody>
                  {account.unassigned.map(b => (
                    <tr key={b.booking_id}>
                      <td>{day(b.booking_date)}</td>
                      <td className="td-wrap">{b.booking_id
                        ? <Link to={entityHref('booking', b.booking_id)}>{b.payment_text || 'Buchung öffnen'}</Link>
                        : b.payment_text || '—'}</td>
                      <td className="text-right td-num">{eur(b.amount)}</td>
                      <td className="text-right td-num">{eur(b.unassigned)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-muted" style={{ padding: '0 1rem 1rem' }}>
                <Link to={unassignedHref}>Nicht zugeordnete Buchungen bis zum Stichtag öffnen</Link> und dort „Aufteilen“ wählen.
              </p>
            </div>
          )}
      </section>
      {editing && tenant && <FormModal title="Mieter bearbeiten" fields={TENANT_FIELDS} initial={tenant}
        onSave={async data => { await api.put(`/tenants/${encodeURIComponent(id)}`, data);
          store?.invalidateRelated('tenants', 'contracts'); setRevision(value => value + 1); }}
        onClose={() => setEditing(false)} />}
    </div>
  );
}

// Who the tenant is and how they pay, at a glance; "Mieter bearbeiten" changes it here.
function TenantFacts({ tenant }) {
  const address = [tenant.address_line, [tenant.postal_code, tenant.city].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  const payment = PAYMENT_METHODS.find(option => option.value === tenant.payment_method)?.label;
  const facts = [['E-Mail', tenant.email && <a href={`mailto:${tenant.email}`}>{tenant.email}</a>],
    ['Telefon', tenant.phone && <a href={`tel:${tenant.phone}`}>{tenant.phone}</a>], ['Anschrift', address],
    ['Zahlungsart', payment],
    ['SEPA-Mandat', tenant.sepa_mandate && [tenant.sepa_mandate, tenant.sepa_mandate_date && `vom ${day(tenant.sepa_mandate_date)}`].filter(Boolean).join(' ')],
    ['Lastschriftkonto', tenant.sepa_iban && [tenant.sepa_iban.replace(/(.{4})/g, '$1 ').trim(), tenant.sepa_account_holder && `(${tenant.sepa_account_holder})`].filter(Boolean).join(' ')],
  ].filter(([, value]) => value);
  if (!facts.length) return null;
  return <section className="card" aria-label="Stammdaten" style={{ marginBottom: '1rem' }}><div className="card-body">
    <dl className="overview-dl">{facts.map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}</dl>
  </div></section>;
}
