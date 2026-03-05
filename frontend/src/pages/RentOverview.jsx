import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import FormModal from '../components/FormModal';

function fmt(v) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(v || 0);
}

const COLUMNS = [
  { key: 'contract_number', label: 'Vertrag', filterType: 'text' },
  { key: 'tenant_name', label: 'Mieter', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'month', label: 'Monat', filterType: 'text' },
  { key: 'total_due', label: 'Forderung (€)', type: 'number', align: 'right',
    render: v => v != null ? fmt(v) : '—' },
  { key: 'amount_paid', label: 'Bezahlt (€)', type: 'number', align: 'right',
    render: v => v != null ? fmt(v) : '—' },
  { key: 'remaining', label: 'Offen (€)', type: 'number', align: 'right',
    render: (v) => {
      const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
      return <span className={cls}>{fmt(v)}</span>;
    }},
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function RentOverview() {
  const [charges, setCharges] = useState([]);
  const [receivables, setReceivables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [paymentModal, setPaymentModal] = useState(null);
  const [tab, setTab] = useState('charges');

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/rent-charges').catch(() => []),
      api.get('/receivables').catch(() => []),
      api.get('/contracts').catch(() => []),
      api.get('/tenants').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([chargesList, recList, contracts, tenants, units]) => {
      const contractMap = Object.fromEntries((contracts || []).map(c => [c.id, c]));
      const tenantMap = Object.fromEntries((tenants || []).map(t => [t.id, t]));
      const unitMap = Object.fromEntries((units || []).map(u => [u.id, u]));

      const enrichedCharges = (chargesList || []).map(r => {
        const contract = contractMap[r.contract_id] || {};
        const tenant = tenantMap[contract.tenant_id] || {};
        const unit = unitMap[contract.unit_id] || {};
        const totalDue = (r.cold_rent || 0) + (r.service_charge || 0) + (r.heating_charge || 0) + (r.other_charges || 0);
        return {
          ...r, _type: 'charge',
          contract_number: contract.contract_number || '—',
          tenant_name: tenant.full_name || '—',
          unit_label: unit.label || '—',
          total_due: totalDue,
          remaining: totalDue - (r.amount_paid || 0),
        };
      });

      const enrichedReceivables = (recList || []).map(r => {
        const contract = contractMap[r.contract_id] || {};
        const tenant = tenantMap[contract.tenant_id] || {};
        const unit = unitMap[contract.unit_id] || {};
        return {
          ...r, _type: 'receivable',
          contract_number: contract.contract_number || '—',
          tenant_name: tenant.full_name || '—',
          unit_label: unit.label || '—',
          month: r.due_date?.slice(0, 7) || '—',
          total_due: r.amount_due || 0,
          amount_paid: r.amount_paid || 0,
          remaining: (r.amount_due || 0) - (r.amount_paid || 0),
        };
      });

      setCharges(enrichedCharges);
      setReceivables(enrichedReceivables);
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleRecordPayment = async (formData) => {
    if (paymentModal._type === 'charge') {
      const newPaid = (paymentModal.amount_paid || 0) + Number(formData.payment_amount);
      const newStatus = newPaid >= paymentModal.total_due ? 'paid' : 'partial';
      await api.patch(`/rent-charges/${paymentModal.id}`, {
        amount_paid: newPaid,
        status: newStatus,
      });
    } else {
      await api.patch(`/receivables/${paymentModal.id}`, {
        status: Number(formData.payment_amount) >= paymentModal.remaining ? 'paid' : 'partial',
      });
    }
    loadData();
  };

  const paymentFields = [
    { key: 'payment_amount', label: 'Zahlungsbetrag (€)', type: 'number', required: true },
    { key: 'payment_date', label: 'Zahlungsdatum', type: 'date', required: true },
    { key: 'payment_note', label: 'Bemerkung', type: 'textarea' },
  ];

  if (loading) return <div className="page-loading">Laden...</div>;
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;

  const data = tab === 'charges' ? charges : receivables;
  const allData = [...charges, ...receivables];
  const totalDue = allData.reduce((s, r) => s + (r.total_due || 0), 0);
  const totalPaid = allData.reduce((s, r) => s + (r.amount_paid || 0), 0);
  const totalOpen = totalDue - totalPaid;
  const overdueCount = allData.filter(r => r.status === 'overdue').length;

  return (
    <div className="page">
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <div className="stat-card">
          <div className="stat-label">Gesamtforderungen</div>
          <div className="stat-value">{fmt(totalDue)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Bezahlt</div>
          <div className="stat-value text-green">{fmt(totalPaid)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Offen</div>
          <div className="stat-value text-red">{fmt(totalOpen)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Überfällig</div>
          <div className="stat-value">{overdueCount} <StatusBadge status="overdue" /></div>
        </div>
      </div>

      <div className="tab-bar" style={{ marginBottom: '1rem' }}>
        <button
          className={`detail-tab ${tab === 'charges' ? 'active' : ''}`}
          onClick={() => setTab('charges')}
        >
          Sollstellungen ({charges.length})
        </button>
        <button
          className={`detail-tab ${tab === 'receivables' ? 'active' : ''}`}
          onClick={() => setTab('receivables')}
        >
          Forderungen ({receivables.length})
        </button>
      </div>

      <DataTable
        title="Mietübersicht"
        columns={COLUMNS}
        data={data}
        onEdit={row => setPaymentModal(row)}
      />

      {paymentModal && (
        <FormModal
          title={`Zahlung erfassen — ${paymentModal.tenant_name} (${paymentModal.month || '—'})`}
          fields={paymentFields}
          initial={{ payment_amount: paymentModal.remaining, payment_date: new Date().toISOString().slice(0, 10) }}
          onSave={handleRecordPayment}
          onClose={() => setPaymentModal(null)}
        />
      )}
    </div>
  );
}
