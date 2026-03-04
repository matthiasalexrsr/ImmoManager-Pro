import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';

const COLUMNS = [
  { key: 'property_name', label: 'Immobilie', filterType: 'text' },
  { key: 'period_label', label: 'Abrechnungszeitraum', filterType: 'text' },
  { key: 'total_costs', label: 'Gesamtkosten (€)', type: 'number', align: 'right',
    render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
  { key: 'units_count', label: 'Einheiten', type: 'number' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select' },
];

export default function Statements() {
  const [periods, setPeriods] = useState([]);
  const [costItems, setCostItems] = useState([]);
  const [statements, setStatements] = useState([]);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const loadData = () => {
    Promise.all([
      api.get('/billing/periods').catch(() => []),
      api.get('/billing/cost-items').catch(() => []),
      api.get('/billing/utility-statements').catch(() => []),
      api.get('/properties').catch(() => []),
    ]).then(([bp, ci, us, props]) => {
      setPeriods(bp);
      setCostItems(ci);
      setStatements(us);
      setProperties(props);

      // There is no single "statement" entity; billing periods serve that role
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));

  // Enrich billing periods with cost totals
  const enriched = periods.map(bp => {
    const costs = costItems.filter(ci => ci.billing_period_id === bp.id);
    const totalCosts = costs.reduce((s, c) => s + (c.amount || 0), 0);
    const stmts = statements.filter(s => s.billing_period_id === bp.id);
    return {
      ...bp,
      property_name: propMap[bp.property_id]?.name || '—',
      period_label: `${bp.start_date || '?'} – ${bp.end_date || '?'}`,
      total_costs: totalCosts,
      units_count: stmts.length,
    };
  });

  const fields = [
    { key: 'property_id', label: 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'start_date', label: 'Beginn', type: 'date', required: true },
    { key: 'end_date', label: 'Ende', type: 'date', required: true },
    { key: 'status', label: 'Status', type: 'select', default: 'draft', options: [
      { value: 'draft', label: 'Entwurf' },
      { value: 'finalized', label: 'Abgeschlossen' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/billing/periods', data);
    } else {
      await api.put(`/billing/periods/${modal.id}`, data);
    }
    loadData();
  };

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
      <DataTable
        title="Nebenkostenabrechnungen"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Abrechnung erstellen' : 'Abrechnung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
