import { useState, useEffect } from 'react';
import { api } from '../api';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate } from '../utils/format';
import { bulkDelete } from '../utils/bulkActions';
import KpiAction from '../components/KpiAction';
const STATUS_LABELS = { new: 'Neu', contacted: 'Kontaktiert', viewing_scheduled: 'Besichtigung geplant', offer_sent: 'Angebot gesendet', accepted: 'Angenommen', rejected: 'Abgelehnt' };

const PRIORITY_COLORS = { 1: 'var(--danger)', 2: 'var(--warning)', 3: 'var(--info)' };

const COLUMNS = [
  { key: 'priority', label: 'Prio', filterType: 'select', align: 'center',
    render: v => {
      const p = Number(v) || 0;
      if (!p) return <span style={{ color: 'var(--text-secondary)' }}>—</span>;
      return (
        <span style={{
          display: 'inline-block', width: 24, height: 24, lineHeight: '24px',
          borderRadius: '50%', textAlign: 'center', fontSize: 'var(--text-2xs)', fontWeight: 700,
          background: PRIORITY_COLORS[p] || 'var(--text-secondary)', color: '#fff',
        }}>
          {p}
        </span>
      );
    }},
  { key: 'full_name', label: 'Name', filterType: 'text' },
  { key: 'email', label: 'E-Mail', filterType: 'text' },
  { key: 'phone', label: 'Telefon' },
  { key: 'source', label: 'Quelle', filterType: 'select' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
  { key: 'unit_label', label: 'Einheit', filterType: 'text', link: 'unit' },
  { key: 'created_at', label: 'Erstellt', type: 'date',
    render: v => formatDate(v) },
];

export default function Leads() {
  const [, setSearchParams] = useSearchParams();
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [leads, setLeads] = useState([]);
  const [units, setUnits] = useState([]);
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [groupBy, setGroupBy] = useState('none');
  const [statusFilter, setStatusFilter] = useState('all');
  const [drilldown, setDrilldown] = useState(0);
  const [loadError, setLoadError] = useState(null);
  const [revision, setRevision] = useState(0);
  const openSources = value => { setSearchParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('suche'); return next; }); setStatusFilter(value); setGroupBy('none'); setDrilldown(number => number + 1); };

  const refreshData = () => setRevision(value => value + 1);

  useEffect(() => {
    const request = new AbortController(); setLoading(true); setLoadError(null);
    Promise.allSettled(['/leads', '/units', '/listings'].map(path => api.list(path, { signal: request.signal }))).then(results => {
      if (request.signal.aborted) return;
      const setters = [setLeads, setUnits, setListings]; const failures = [];
      results.forEach((result, index) => {
        if (result.status === 'fulfilled' && Array.isArray(result.value)) setters[index](result.value);
        else failures.push(result.reason?.message || 'Die Quelldaten konnten nicht gelesen werden.');
      });
      if (failures.length) setLoadError(failures.join(' · '));
    }).finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision]);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = leads.map(l => ({
    ...l,
    unit_label: unitMap[l.unit_id]?.label || '—',
  }));

  // Sort by priority (higher priority = lower number = first), then by name
  const sorted = enriched.filter(row => statusFilter === 'all' || row.status === statusFilter).sort((a, b) => {
    const pa = a.priority || 99;
    const pb = b.priority || 99;
    if (pa !== pb) return pa - pb;
    return (a.full_name || '').localeCompare(b.full_name || '');
  });

  // Group leads
  const getGrouped = () => {
    if (groupBy === 'none') return [{ label: null, leads: sorted }];

    const groups = {};
    sorted.forEach(l => {
      let key;
      if (groupBy === 'unit') key = l.unit_label || 'Keine Einheit';
      else if (groupBy === 'status') key = l.status || 'Unbekannt';
      if (!groups[key]) groups[key] = [];
      groups[key].push(l);
    });

    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, leads]) => ({ label, leads }));
  };

  const fields = [
    { key: 'full_name', label: 'Name', required: true },
    { key: 'email', label: 'E-Mail' },
    { key: 'phone', label: 'Telefon' },
    { key: 'source', label: 'Quelle', type: 'select', options: [
      { value: 'portal', label: 'Portal' },
      { value: 'website', label: 'Website' },
      { value: 'referral', label: 'Empfehlung' },
      { value: 'direct', label: 'Direkt' },
      { value: 'other', label: 'Sonstiges' },
    ]},
    { key: 'unit_id', label: 'Einheit', type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'listing_id', label: 'Inserat', type: 'select',
      options: listings.map(l => ({ value: l.id, label: l.title })) },
    { key: 'priority', label: 'Priorität', type: 'select', default: '0', options: [
      { value: '0', label: 'Keine' },
      { value: '1', label: '1 — Hoch' },
      { value: '2', label: '2 — Mittel' },
      { value: '3', label: '3 — Niedrig' },
    ]},
    { key: 'status', label: 'Status', type: 'select', default: 'new', options: [
      { value: 'new', label: 'Neu' },
      { value: 'contacted', label: 'Kontaktiert' },
      { value: 'viewing_scheduled', label: 'Besichtigung geplant' },
      { value: 'offer_sent', label: 'Angebot gesendet' },
      { value: 'accepted', label: 'Angenommen' },
      { value: 'rejected', label: 'Abgelehnt' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    const payload = { ...data, priority: Number(data.priority) || 0 };
    if (modal === 'create') {
      await api.post('/leads', payload);
    } else {
      await api.put(`/leads/${modal.id}`, payload);
    }
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.full_name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/leads/${row.id}`);
      refreshData();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  // only the first load replaces the list; a reload keeps the tables (their search, selection, results)
  if (loading && leads.length === 0 && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;

  const statusCounts = leads.reduce((acc, l) => { acc[l.status] = (acc[l.status] || 0) + 1; return acc; }, {});
  const grouped = getGrouped();

  return (
    <div className="page">
      {loadError && <p role="alert">{loadError} <button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></p>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Summary stats */}
      <div className="kpi-row">
        <KpiAction label="Gesamt" value={loadError && !leads.length ? '—' : leads.length} onClick={() => openSources('all')} />
        {Object.entries(statusCounts).map(([status, count]) => (
          <KpiAction key={status} label={STATUS_LABELS[status] || status || 'Ohne Status'} value={count} onClick={() => openSources(status)} />
        ))}
      </div>

      {/* Group-by controls */}
      <div className="toolbar">
        <span className="toolbar-label">Gruppieren nach:</span>
        {[
          { value: 'none', label: 'Keine' },
          { value: 'unit', label: 'Einheit' },
          { value: 'status', label: 'Status' },
        ].map(opt => (
          <button
            key={opt.value}
            className={`btn btn-sm ${groupBy === opt.value ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setGroupBy(opt.value)}
            style={{ fontSize: 'var(--text-xs)', padding: '4px 10px' }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Lead tables */}
      {grouped.map((group, gi) => (
        <div key={gi} style={{ marginBottom: group.label ? '2rem' : 0 }}>
          {group.label && (
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: 'var(--text-lg)', borderBottom: '2px solid var(--primary)', paddingBottom: '0.25rem' }}>
              {group.label} ({group.leads.length})
            </h3>
          )}
          <DataTable
            title={group.label ? '' : 'Interessenten'}
            columns={COLUMNS}
            data={group.leads}
            drilldownKey={drilldown}
            emptyText={loadError && !leads.length ? 'Interessenten noch nicht verfügbar.' : undefined}
            viewConfig={{ column_filters: { lead_status: statusFilter } }}
            onApplyView={config => setStatusFilter(config.column_filters?.lead_status || 'all')}
        rowName={row => row.full_name || row.id}
        bulkActions={[bulkDelete({ one: 'Interessent', many: 'Interessenten', remove: row => api.del(`/leads/${row.id}`),
          finished: () => refreshData() })]}
            onAdd={gi === 0 ? () => setModal('create') : undefined}
            onEdit={row => setModal(row)}
            onDelete={handleDelete}
          />
        </div>
      ))}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Interessent erstellen' : 'Interessent bearbeiten'}
          repeatKeep={['source', 'unit_id', 'listing_id']}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
