import { useState, useEffect, useMemo, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate, formatMoney } from '../utils/format';
import { bulkDelete } from '../utils/bulkActions';
import KpiAction from '../components/KpiAction';

const FILTERS = ['all', 'open', 'in_progress', 'completed', 'cancelled', 'overdue', 'urgent', 'no_appointment', 'no_assignee', 'age_basis', 'escalation'];
const today = () => { const value = new Date(); value.setHours(0, 0, 0, 0); return value; };

function ageDays(createdAt) {
  if (!createdAt) return null;
  return Math.floor((today() - new Date(createdAt)) / (1000 * 60 * 60 * 24));
}

function isOverdue(row) {
  if (!row.due_date) return false;
  const due = new Date(row.due_date);
  due.setHours(0, 0, 0, 0);
  return due < today() && ['open', 'in_progress', 'pending', 'review'].includes(String(row.status || '').toLowerCase());
}

export default function Maintenance() {
  const [params, setParams] = useSearchParams();
  const requestedFilter = params.get('status') || params.get('filter') || 'all';
  const linkedFilter = FILTERS.includes(requestedFilter) ? requestedFilter : 'all';
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // values a New form starts with when opened from elsewhere (the property page's "Einheit anlegen")
  const [prefill, setPrefill] = useState(null);
  const [filter, setFilter] = useState(linkedFilter);
  const [drilldown, setDrilldown] = useState(0);
  const [error, setError] = useState(null);
  const [source, setSource] = useState({ items: [], loading: false, error: null });
  const [sourceAttempt, setSourceAttempt] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const openSources = key => {
    setFilter(key); setDrilldown(value => value + 1);
    setParams(current => { const next = new URLSearchParams(current); ['filter', 'status', 'focus_id', 'suche'].forEach(name => next.delete(name));
      if (key !== 'all') next.set(['open', 'in_progress', 'completed', 'cancelled'].includes(key) ? 'status' : 'filter', key); return next; });
  };
  useEffect(() => { setFilter(linkedFilter); setDrilldown(value => value + 1); }, [linkedFilter, params]);

  const refreshData = useCallback(() => {
    setAttempt(value => value + 1); setSourceAttempt(value => value + 1);
  }, []);

  useEffect(() => {
    const request = new AbortController(); setLoading(true); setError(null);
    api.list('/maintenance', { signal: request.signal })
      .then(data => { if (!Array.isArray(data)) throw new Error('Die Wartungsfälle konnten nicht gelesen werden.'); if (!request.signal.aborted) setItems(data); })
      .catch(failure => { if (!request.signal.aborted) setError(failure.message); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [attempt]);
  useEffect(() => {
    if (filter !== 'escalation') return;
    const request = new AbortController(); setSource(current => ({ ...current, loading: true, error: null }));
    api.list('/maintenance?workflow_filter=escalation', { signal: request.signal }).then(data => {
      if (!Array.isArray(data)) throw new Error('Die Eskalationsquelle konnte nicht gelesen werden.');
      if (!request.signal.aborted) setSource({ items: data, loading: false, error: null });
    }).catch(failure => { if (!request.signal.aborted) setSource(current => ({ ...current, loading: false, error: failure.message })); });
    return () => request.abort();
  }, [filter, sourceAttempt]);

  // Lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));

  // Enrich data
  const enrich = rows => rows.filter(row => (!params.get('property_id') || row.property_id === params.get('property_id'))
    && (!params.get('unit_id') || row.unit_id === params.get('unit_id'))).map(row => ({
    ...row,
    property_name: propMap[row.property_id] || '—',
    unit_label: unitMap[row.unit_id] || '—',
    age_days: ageDays(row.created_at),
  }));
  const enriched = enrich(items);
  const escalations = enrich(source.items);

  // Filter logic
  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'open') return enriched.filter(r => r.status === 'open');
    if (filter === 'in_progress') return enriched.filter(r => r.status === 'in_progress');
    if (filter === 'completed' || filter === 'cancelled') return enriched.filter(r => r.status === filter);
    if (filter === 'age_basis') return enriched.filter(r => r.status === 'open' || r.status === 'in_progress');
    if (filter === 'escalation') return escalations;
    if (filter === 'overdue') return enriched.filter(r => isOverdue(r));
    if (filter === 'urgent') return enriched.filter(r => r.priority === 'urgent' || r.priority === 'high');
    if (filter === 'no_appointment') return enriched.filter(r => !r.appointment_at);
    if (filter === 'no_assignee') return enriched.filter(r => !r.assignee);
    return enriched;
  }, [enriched, filter, escalations]);

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
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text', link: 'unit', subLink: 'property' },
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

  // only the first load replaces the list; a reload keeps the table (its search, selection, results)
  if (loading && items.length === 0 && !error && !modal) return <div className="page-loading">Lade Wartungsaufträge...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.maintenance.title') || 'Wartung & Instandhaltung'}</h1>
      {error && <p role="alert">{error} <button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></p>}
      {filter === 'escalation' && <><p className="text-muted">Fälle mit aktiver Instandhaltungsregel, erreichtem Überfälligkeitsgrenzwert und Status offen, in Bearbeitung, ausstehend oder Prüfung.</p>
        {source.loading && <p role="status">Eskalationsfälle werden geladen…</p>}
        {source.error && <p role="alert">{source.error} <button type="button" onClick={() => setSourceAttempt(value => value + 1)}>Eskalationsquelle erneut laden</button></p>}</>}

      {/* Summary cards */}
      <div className="kpi-row">
        <KpiAction label="Gesamt" value={error && !items.length ? '—' : totalCount} onClick={() => openSources('all')} />
        <KpiAction label="Offen" value={error && !items.length ? '—' : openCount} color="var(--info)" onClick={() => openSources('open')} />
        <KpiAction label="In Bearbeitung" value={error && !items.length ? '—' : inProgressCount} color="var(--warning)" onClick={() => openSources('in_progress')} />
        <KpiAction label="Überfällig" value={error && !items.length ? '—' : overdueCount} color="var(--danger)" onClick={() => openSources('overdue')} />
        <KpiAction label="Ø Alter (offen / in Bearbeitung)" value={error && !items.length ? '—' : `${avgAge} Tage`} onClick={() => openSources('age_basis')} />
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'in_progress', label: 'In Bearbeitung' },
          { key: 'overdue', label: 'Überfällig' },
          { key: 'escalation', label: 'Eskalationsfälle' },
          { key: 'age_basis', label: 'Basis Durchschnittsalter' },
          { key: 'urgent', label: 'Dringend' },
          { key: 'no_appointment', label: 'Ohne Termin' },
          { key: 'no_assignee', label: 'Ohne Zuständigen' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => openSources(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        title={t('pages.maintenance.title') || 'Wartung & Instandhaltung'}
        columns={columns}
        data={filtered}
        drilldownKey={drilldown}
        emptyText={filter === 'escalation' && (source.loading || source.error) ? 'Eskalationsquelle noch nicht verfügbar.' : undefined}
        viewConfig={{ column_filters: { workflow_filter: filter, property_id: params.get('property_id') || '', unit_id: params.get('unit_id') || '' } }}
        onApplyView={config => { const saved = config.column_filters || {}; setFilter(FILTERS.includes(saved.workflow_filter) ? saved.workflow_filter : 'all');
          setParams(current => { const next = new URLSearchParams(current); ['status', 'filter', 'focus_id', 'suche'].forEach(key => next.delete(key));
            if (FILTERS.includes(saved.workflow_filter) && saved.workflow_filter !== 'all') next.set('filter', saved.workflow_filter);
            ['property_id', 'unit_id'].forEach(key => { if (saved[key]) next.set(key, saved[key]); else next.delete(key); }); return next; }); }}
        rowName={row => row.title || row.id}
        bulkActions={[bulkDelete({ one: 'Wartungsauftrag', many: 'Wartungsaufträge', remove: row => api.del(`/maintenance/${row.id}`),
          finished: () => { refreshData(); store?.invalidateRelated('maintenance', 'properties', 'units'); } })]}
        onAdd={values => { setPrefill(values || null); setModal('create'); }}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Wartungsauftrag erstellen' : 'Wartungsauftrag bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? prefill : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
