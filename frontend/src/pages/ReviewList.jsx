import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../components/Toast';
import StatusBadge from '../components/StatusBadge';

const KIND_LABELS = {
  unit_rent_differs: 'Miete Einheit ≠ Vertrag',
  history_taken_over: 'Mietverlauf übernommen',
  adjustment_not_applied: 'Mietanpassung nicht angewendet',
  unassigned_payment: 'Zahlung ohne Vertrag',
  payment_without_tenant: 'Zahlung ohne Mieter',
};

/** Rents and payments that need a decision, each with a link to where it is fixed. */
export default function ReviewList() {
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [kind, setKind] = useState('all');

  useEffect(() => {
    api.get('/review').then(r => setItems(r?.items || [])).catch(err => { toast.error(err.message); setItems([]); });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!items) return <div className="page-loading">Lade Prüfliste...</div>;
  const counts = items.reduce((c, i) => ({ ...c, [i.kind]: (c[i.kind] || 0) + 1 }), {});
  const shown = kind === 'all' ? items : items.filter(i => i.kind === kind);

  return (
    <div className="page">
      <h1 className="page-title">Prüfliste</h1>
      <p className="text-muted">Mieten und Zahlungen, die eine Entscheidung brauchen.</p>
      <div style={{ display: 'flex', gap: '0.5rem', margin: '1rem 0', flexWrap: 'wrap' }}>
        {[['all', `Alle (${items.length})`], ...Object.entries(KIND_LABELS).map(([k, l]) => [k, `${l} (${counts[k] || 0})`])]
          .map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${kind === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setKind(k)}>{label}</button>
          ))}
      </div>
      {shown.length === 0
        ? <p className="text-muted">Nichts zu prüfen.</p>
        : (
          <div className="card">
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Art</th><th>Was</th><th>Details</th><th></th></tr></thead>
                <tbody>
                  {shown.map(item => (
                    <tr key={`${item.kind}-${item.entity_id}`}>
                      <td><StatusBadge status={item.severity} /> {KIND_LABELS[item.kind] || item.kind}</td>
                      <td>{item.title}</td>
                      <td className="text-muted">{item.detail}</td>
                      <td><Link className="btn btn-sm btn-secondary" to={item.link}>Öffnen</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
    </div>
  );
}
