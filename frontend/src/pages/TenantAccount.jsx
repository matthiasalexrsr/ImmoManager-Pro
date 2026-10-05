import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../components/Toast';
import { formatDate as day, formatMoney } from '../utils/format';

const eur = v => formatMoney(v || 0);

/** Per contract what was due, what was paid and the balance, plus payments not credited to any contract. */
export default function TenantAccount() {
  const { id } = useParams();
  const toast = useToast();
  const [tenant, setTenant] = useState(null);
  const [account, setAccount] = useState(null);
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));

  useEffect(() => {
    api.get(`/tenants/${id}`).then(setTenant).catch(err => toast.error(err.message));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.get(`/tenants/${id}/account?as_of=${asOf}`).then(setAccount).catch(err => toast.error(err.message));
  }, [id, asOf]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!account) return <div className="page-loading">Lade Mieterkonto...</div>;

  const totals = account.contracts.reduce((s, c) => ({
    expected: s.expected + c.expected, paid: s.paid + c.paid,
    balance: s.balance + c.outstanding - c.overpaid,
  }), { expected: 0, paid: 0, balance: 0 });
  const unassigned = account.unassigned.reduce((s, b) => s + b.unassigned, 0);

  return (
    <div className="page">
      <h1 className="page-title">Mieterkonto {tenant?.full_name || ''}</h1>
      <div className="toolbar">
        <label htmlFor="as-of">Stichtag</label>
        <input id="as-of" type="date" value={asOf} onChange={e => setAsOf(e.target.value)} />
        <Link to="/tenants" className="btn btn-sm btn-secondary">Zurück zu den Mietern</Link>
      </div>

      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <div className="stat-card"><div className="stat-label">Soll</div><div className="stat-value">{eur(totals.expected)}</div></div>
        <div className="stat-card"><div className="stat-label">Gezahlt (zugeordnet)</div><div className="stat-value">{eur(totals.paid)}</div></div>
        <div className="stat-card">
          <div className="stat-label">{totals.balance >= 0 ? 'Offen' : 'Guthaben'}</div>
          <div className={`stat-value ${totals.balance > 0 ? 'text-red' : 'text-green'}`}>{eur(Math.abs(totals.balance))}</div>
        </div>
        <div className="stat-card"><div className="stat-label">Nicht zugeordnet</div><div className="stat-value">{eur(unassigned)}</div></div>
      </div>

      <div className="card" style={{ marginBottom: '1rem' }}>
        <div className="card-header"><strong>Verträge</strong></div>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Vertrag</th><th className="text-right">Soll</th><th className="text-right">Gezahlt</th><th className="text-right">Offen</th><th className="text-right">Überzahlt</th></tr></thead>
            <tbody>
              {account.contracts.map(c => (
                <tr key={c.contract_id}>
                  <td>{c.contract_number}</td>
                  <td className="text-right td-num">{eur(c.expected)}</td>
                  <td className="text-right td-num">{eur(c.paid)}</td>
                  <td className={`text-right td-num ${c.outstanding > 0 ? 'text-red' : ''}`}>{eur(c.outstanding)}</td>
                  <td className={`text-right td-num ${c.overpaid > 0 ? 'text-green' : ''}`}>{eur(c.overpaid)}</td>
                </tr>
              ))}
              {account.contracts.length === 0 && <tr><td colSpan={5} className="table-empty">Keine Verträge</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
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
                      <td className="td-wrap">{b.payment_text || '—'}</td>
                      <td className="text-right td-num">{eur(b.amount)}</td>
                      <td className="text-right td-num">{eur(b.unassigned)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-muted" style={{ padding: '0 1rem 1rem' }}>
                Zuordnen unter <Link to="/bookings">Buchungen</Link> → Filter „Nicht zugeordnet“ → „Aufteilen“.
              </p>
            </div>
          )}
      </div>
    </div>
  );
}
