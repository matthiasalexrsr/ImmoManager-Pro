import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import KpiAction from '../components/KpiAction';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

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
  { key: 'property_name', label: 'Immobilie', filterType: 'text', link: 'property' },
  { key: 'year', label: 'Jahr', filterType: 'select' },
  { key: 'category', label: 'Kategorie', filterType: 'select',
    render: v => {
      const labels = { maintenance: 'Instandhaltung', operating_costs: 'Betriebskosten', renovation: 'Renovierung', reserve: 'Rücklage', other: 'Sonstiges' };
      return labels[v] || v;
    }},
  { key: 'planned_amount', label: 'Geplant (€)', type: 'number', sum: true, align: 'right',
    render: v => fmt(v) },
  { key: 'actual_amount', label: 'Tatsächlich (€)', type: 'number', sum: true, align: 'right',
    render: v => fmt(v) },
  { key: 'variance', label: 'Abweichung (€)', type: 'number', align: 'right',
    render: (v) => {
      const cls = v > 0 ? 'text-red' : v < 0 ? 'text-green' : '';
      return <span className={cls}>{fmt(v)}</span>;
    }},
];

export default function Budgets() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const [budgets, setBudgets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [drilldown, setDrilldown] = useState(0);
  const showSources = () => setDrilldown(value => value + 1);

  const refreshData = () => {
    setLoadError(null);
    api.list('/budgets')
      .then(b => { if (!Array.isArray(b)) throw new Error('Budgets konnten nicht gelesen werden.'); setBudgets(b); })
      .catch(e => setLoadError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    setLoadError(null); setLoading(true);
    api.list('/budgets')
      .then(data => { if (!Array.isArray(data)) throw new Error('Budgets konnten nicht gelesen werden.'); if (!cancelled) setBudgets(data); })
      .catch(e => { if (!cancelled) setLoadError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p]));
  const enriched = budgets.map(b => ({
    ...b,
    property_name: propMap[b.property_id]?.name || '—',
    variance: (b.actual_amount || 0) - (b.planned_amount || 0),
  }));

  const totalPlanned = enriched.reduce((s, b) => s + Math.round(Number(b.planned_amount || 0) * 100), 0) / 100;
  const totalActual = enriched.reduce((s, b) => s + Math.round(Number(b.actual_amount || 0) * 100), 0) / 100;

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
    refreshData();
    if (store) store.invalidateRelated('budgets');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.property_name} ${row.year}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/budgets/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('budgets');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (loadError && !modal) return <div className="page"><div className="alert alert-error" role="alert">{loadError}<button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div></div>;

  return (
    <div className="page">
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <KpiAction label="Geplant gesamt" value={fmt(totalPlanned)} onClick={showSources} />
        <KpiAction label="Tatsächlich gesamt" value={fmt(totalActual)} onClick={showSources} />
        <KpiAction label="Abweichung" value={fmt(totalActual - totalPlanned)} onClick={showSources} />
      </div>
      <p className="text-muted">Grundlage: die geplanten und erfassten Istbeträge der unten aufgeführten Budgetpositionen.</p>

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
        drilldownKey={drilldown}
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
