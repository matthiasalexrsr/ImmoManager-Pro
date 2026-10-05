import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useToast } from '../components/Toast';

const KIND_LABELS = {
  unit_rent_differs: 'Miete Einheit ≠ Vertrag',
  history_taken_over: 'Mietverlauf übernommen',
  adjustment_not_applied: 'Mietanpassung nicht angewendet',
  unassigned_payment: 'Zahlung ohne Vertrag',
  payment_without_tenant: 'Zahlung ohne Mieter',
  deposit_too_high: 'Kaution zu hoch',
  increase_over_cap: 'Kappungsgrenze',
  adjustment_mid_month: 'Anpassung nicht zum 1.',
  statement_period_too_long: 'Abrechnungszeitraum',
  invoice_due_before_date: 'Fälligkeit vor Datum',
  rent_decrease: 'Mietsenkung',
  invoice_negative: 'Negativer Rechnungsbetrag',
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
      <p className="page-subtitle">Mieten und Zahlungen, die eine Entscheidung brauchen.</p>
      <div className="filter-chips">
        {[['all', `Alle (${items.length})`],
          ...Object.entries(KIND_LABELS).filter(([k]) => counts[k] || kind === k).map(([k, l]) => [k, `${l} (${counts[k] || 0})`])]
          .map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${kind === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setKind(k)}>{label}</button>
          ))}
      </div>
      {shown.length === 0
        ? <p className="text-muted">Nichts zu prüfen.</p>
        : (
          <div className="data-table-wrapper">
            <div className="table-scroll">
              <table>
                <thead><tr><th>Art</th><th>Hinweis</th><th /></tr></thead>
                <tbody>
                  {shown.map(item => (
                    <tr key={`${item.kind}-${item.entity_id}`}>
                      <td>
                        <span className={`badge ${item.severity === 'warning' ? 'badge-yellow' : 'badge-blue'}`}>
                          {KIND_LABELS[item.kind] || item.kind}
                        </span>
                      </td>
                      <td className="td-wrap td-stacked">
                        <div className="td-title">{item.title}</div>
                        <div className="td-sub">{item.detail}</div>
                      </td>
                      <td className="text-right"><Link className="btn btn-sm btn-secondary" to={item.link}>Öffnen</Link></td>
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
