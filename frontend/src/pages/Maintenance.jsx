import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate, formatMoney } from '../utils/format';

const TODAY = new Date();
TODAY.setHours(0, 0, 0, 0);

function ageDays(createdAt) {
  if (!createdAt) return null;
  return Math.floor((TODAY - new Date(createdAt)) / (1000 * 60 * 60 * 24));
}

function isOverdue(row) {
  if (!row.due_date) return false;
  const due = new Date(row.due_date);
  due.setHours(0, 0, 0, 0);
  return due < TODAY && (row.status === 'open' || row.status === 'in_progress');
}

export default function Maintenance() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const refreshData = () => {
    setLoading(true);
    api.list('/maintenance').catch(() => [])
      .then(data => setItems(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.list('/maintenance').catch(() => [])
      .then(data => { if (!cancelled) setItems(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));

  // Enrich data
  const enriched = items.map(row => ({
    ...row,
    property_name: propMap[row.property_id] || '—',
    unit_label: unitMap[row.unit_id] || '—',
    age_days: ageDays(row.created_at),
  }));

  // Filter logic
  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'open') return enriched.filter(r => r.status === 'open');
    if (filter === 'in_progress') return enriched.filter(r => r.status === 'in_progress');
    if (filter === 'overdue') return enriched.filter(r => isOverdue(r));
    if (filter === 'urgent') return enriched.filter(r => r.priority === 'urgent' || r.priority === 'high');
    if (filter === 'no_appointment') return enriched.filter(r => !r.appointment_at);
    if (filter === 'no_assignee') return enriched.filter(r => !r.assignee);
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const openCount = enriched.filter(r => r.status === 'open').length;
  const inProgressCount = enriched.filter(r => r.status === 'in_progress').length;
  const overdueCount = enriched.filter(r => isOverdue(r)).length;

  const openOrInProgress = enriched.filter(r => r.status === 'open' || r.status === 'in_progress');
  const avgAge = openOrInProgress.length > 0
    ? Math.max(0, Math.round(openOrInProgress.reduce((sum, r) => sum + Math.max(0, r.age_days || 0), 0) / openOrInProgress.length))
    : 0;

  const columns = [
    { key: 'title', label: t('pages.maintenance.columns.title') || 'Titel', filterType: 'text',
      // the case is the project file: work packages, quotes, orders, invoices, protocols
      render: (v, row) => <Link to={`/maintenance/${encodeURIComponent(row.id)}`}>{v || row.id}</Link> },
    { key: 'property_name', hidden: true, label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text' },
    { key: 'category', hidden: true, label: t('pages.maintenance.columns.category') || 'Kategorie', filterType: 'select' },
    { key: 'priority', label: t('pages.maintenance.columns.priority') || 'Priorität', type: 'status', filterType: 'select' },
    { key: 'assignee', hidden: true, label: t('pages.maintenance.columns.assignee') || 'Zuständig', filterType: 'text' },
    { key: 'contractor', label: t('pages.maintenance.form.contractor') || 'Handwerker', filterType: 'text' },
    { key: 'reported_by', hidden: true, label: t('pages.maintenance.form.reportedBy') || 'Gemeldet von', filterType: 'text' },
    { key: 'due_date', label: t('pages.maintenance.columns.dueDate') || 'Fällig am', type: 'date', filterType: 'dateRange',
      render: (v, row) => {
        if (!v) return '—';
        const display = formatDate(v);
        if (isOverdue(row)) {
          return <span style={{ color: 'var(--danger)', fontWeight: 700 }}>{display}</span>;
        }
        return display;
      }},
    { key: 'appointment_at', hidden: true, label: t('pages.maintenance.form.appointment') || 'Termin', type: 'date', filterType: 'dateRange' },
    { key: 'age_days', hidden: true, label: 'Alter (Tage)', type: 'number', align: 'right',
      render: v => v != null ? `${v} T` : '—' },
    { key: 'estimated_cost', label: t('pages.maintenance.columns.cost') || 'Kosten (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'status', label: t('pages.maintenance.columns.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'property_id', label: t('pages.maintenance.form.property') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('pages.maintenance.form.unit') || 'Einheit', type: 'select',
      options: [{ value: '', label: t('pages.maintenance.form.noneOption') || '— Keine —' }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'title', label: t('pages.maintenance.form.title') || 'Titel', required: true },
    { key: 'description', label: t('pages.maintenance.form.description') || 'Beschreibung', type: 'textarea' },
    { key: 'category', label: t('pages.maintenance.form.category') || 'Kategorie', type: 'select', options: [
      { value: 'Sanitär', label: t('pages.maintenance.categories.plumbing') || 'Sanitär' },
      { value: 'Elektrik', label: t('pages.maintenance.categories.electrical') || 'Elektrik' },
      { value: 'Heizung', label: t('pages.maintenance.categories.heating') || 'Heizung' },
      { value: 'Dach', label: t('pages.maintenance.categories.roof') || 'Dach' },
      { value: 'Fassade', label: t('pages.maintenance.categories.facade') || 'Fassade' },
      { value: 'Sonstiges', label: t('pages.maintenance.categories.other') || 'Sonstiges' },
    ]},
    { key: 'priority', label: t('pages.maintenance.form.priority') || 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: t('pages.maintenance.priority.low') || 'Niedrig' },
      { value: 'medium', label: t('pages.maintenance.priority.medium') || 'Mittel' },
      { value: 'high', label: t('pages.maintenance.priority.high') || 'Hoch' },
      { value: 'urgent', label: t('pages.maintenance.priority.urgent') || 'Dringend' },
    ]},
    { key: 'reported_by', label: t('pages.maintenance.form.reportedBy') || 'Gemeldet von' },
    { key: 'assignee', label: t('pages.maintenance.form.assignee') || 'Zuständig' },
    { key: 'contractor', label: t('pages.maintenance.form.contractor') || 'Handwerker' },
    { key: 'due_date', label: t('pages.maintenance.form.dueDate') || 'Fällig am', type: 'date' },
    { key: 'appointment_at', label: t('pages.maintenance.form.appointment') || 'Termin', type: 'date' },
    { key: 'estimated_cost', label: t('pages.maintenance.form.estimatedCost') || 'Geschätzte Kosten (€)', type: 'number' },
    { key: 'status', label: t('pages.maintenance.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('pages.maintenance.status.open') || 'Offen' },
      { value: 'in_progress', label: t('pages.maintenance.status.inProgress') || 'In Bearbeitung' },
      { value: 'completed', label: t('pages.maintenance.status.completed') || 'Erledigt' },
      { value: 'cancelled', label: t('pages.maintenance.status.cancelled') || 'Abgebrochen' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/maintenance', data);
    } else {
      await api.put(`/maintenance/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('maintenance', 'properties', 'units');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.title}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/maintenance/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('maintenance', 'properties', 'units');
  };

  if (loading) return <div className="page-loading">Lade Wartungsaufträge...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.maintenance.title') || 'Wartung & Instandhaltung'}</h1>

      {/* Summary cards */}
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{totalCount}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--info, #2196f3)' }}>{openCount}</div>
          <div className="kpi-label">Offen</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--warning)' }}>{inProgressCount}</div>
          <div className="kpi-label">In Bearbeitung</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{overdueCount}</div>
          <div className="kpi-label">Überfällig</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{avgAge} Tage</div>
          <div className="kpi-label">&Oslash; Alter offener Fälle</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'in_progress', label: 'In Bearbeitung' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'urgent', label: 'Dringend' },
          { key: 'no_appointment', label: 'Ohne Termin' },
          { key: 'no_assignee', label: 'Ohne Zuständigen' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        title={t('pages.maintenance.title') || 'Wartung & Instandhaltung'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Wartungsauftrag erstellen' : 'Wartungsauftrag bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
