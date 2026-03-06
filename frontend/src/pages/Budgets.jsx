import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

function fmt(v) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(v || 0);
}

const CATEGORY_OPTIONS = [
  { value: 'maintenance', label: 'Instandhaltung' },
  { value: 'operating_costs', label: 'Betriebskosten' },
  { value: 'renovation', label: 'Renovierung' },
  { value: 'reserve', label: 'Rücklage' },
  { value: 'other', label: 'Sonstiges' },
];

const COLUMNS = [
  { key: 'property_name', label: 'Immobilie', filterType: 'text' },
  { key: 'year', label: 'Jahr', filterType: 'select' },
  { key: 'category', label: 'Kategorie', filterType: 'select',
    render: v => {
      const labels = { maintenance: 'Instandhaltung', operating_costs: 'Betriebskosten', renovation: 'Renovierung', reserve: 'Rücklage', other: 'Sonstiges' };
      return labels[v] || v;
    }},
  { key: 'planned_amount', label: 'Geplant (€)', type: 'number', align: 'right',
    render: v => fmt(v) },
  { key: 'actual_amount', label: 'Tatsächlich (€)', type: 'number', align: 'right',
    render: v => fmt(v) },
  { key: 'variance', label: 'Abweichung (€)', type: 'number', align: 'right',
    render: (v) => {
      const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
      return <span className={cls}>{fmt(v)}</span>;
    }},
];

export default function Budgets() {
  const { t } = useTranslation();
  const [budgets, setBudgets] = useState([]);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/budgets').catch(err => { console.warn('[Budgets]', err.message); return []; }),
      api.get('/properties').catch(() => []),
    ]).then(([b, p]) => {
      setBudgets(b || []);
      setProperties(p || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const enriched = budgets.map(b => ({
    ...b,
    property_name: propMap[b.property_id]?.name || '—',
    variance: (b.actual_amount || 0) - (b.planned_amount || 0),
  }));

  const totalPlanned = enriched.reduce((s, b) => s + (b.planned_amount || 0), 0);
  const totalActual = enriched.reduce((s, b) => s + (b.actual_amount || 0), 0);

  const fields = [
    { key: 'property_id', label: 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'year', label: 'Jahr', type: 'number', required: true },
    { key: 'category', label: 'Kategorie', type: 'select', required: true, options: CATEGORY_OPTIONS },
    { key: 'planned_amount', label: 'Geplanter Betrag (€)', type: 'number', required: true },
    { key: 'actual_amount', label: 'Tatsächlicher Betrag (€)', type: 'number' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/budgets', data);
    } else {
      await api.put(`/budgets/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.property_name} ${row.year}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/budgets/${row.id}`);
      loadData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <div className="stat-card">
          <div className="stat-label">Geplant gesamt</div>
          <div className="stat-value">{fmt(totalPlanned)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Tatsächlich gesamt</div>
          <div className="stat-value">{fmt(totalActual)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Abweichung</div>
          <div className={`stat-value ${totalActual > totalPlanned ? 'text-red' : 'text-green'}`}>
            {fmt(totalActual - totalPlanned)}
          </div>
        </div>
      </div>

      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title="Budgets"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Budget erstellen' : 'Budget bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
