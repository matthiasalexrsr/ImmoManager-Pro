import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const PRIORITY_COLORS = { 1: 'var(--danger)', 2: 'var(--warning)', 3: 'var(--info)' };

const COLUMNS = [
  { key: 'priority', label: 'Prio', filterType: 'select', align: 'center',
    render: v => {
      const p = Number(v) || 0;
      if (!p) return <span style={{ color: 'var(--text-secondary)' }}>—</span>;
      return (
        <span style={{
          display: 'inline-block', width: 24, height: 24, lineHeight: '24px',
          borderRadius: '50%', textAlign: 'center', fontSize: '0.75rem', fontWeight: 700,
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
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'created_at', label: 'Erstellt', type: 'date',
    render: v => v ? new Date(v).toLocaleDateString('de-DE') : '—' },
];

export default function Leads() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [leads, setLeads] = useState([]);
  const [units, setUnits] = useState([]);
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [groupBy, setGroupBy] = useState('none');

  const refreshData = () => {
    setLoading(true);
    Promise.all([
      api.get('/leads').catch(err => { console.warn('[Leads]', err.message); return []; }),
      api.get('/units').catch(() => []),
      api.get('/listings').catch(() => []),
    ]).then(([l, u, li]) => {
      setLeads(l || []);
      setUnits(u || []);
      setListings(li || []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get('/leads').catch(err => { console.warn('[Leads]', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Leads] units:', err.message); return []; }),
    ]).then(([l, u]) => {
      if (cancelled) return;
      setLeads(l || []);
      setUnits(u || []);
    }).catch(e => {
      if (!cancelled) console.warn('[Leads] load failed:', e.message);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = leads.map(l => ({
    ...l,
    unit_label: unitMap[l.unit_id]?.label || '—',
  }));

  // Sort by priority (higher priority = lower number = first), then by name
  const sorted = [...enriched].sort((a, b) => {
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

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  const statusCounts = leads.reduce((acc, l) => { acc[l.status] = (acc[l.status] || 0) + 1; return acc; }, {});
  const grouped = getGrouped();

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Summary stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem', textAlign: 'center' }}>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--primary)' }}>{leads.length}</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Gesamt</div>
        </div>
        {Object.entries(statusCounts).map(([status, count]) => (
          <div key={status} className="panel" style={{ padding: '0.75rem', textAlign: 'center' }}>
            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{count}</div>
            <div style={{ fontSize: '0.8rem' }}><StatusBadge status={status} /></div>
          </div>
        ))}
      </div>

      {/* Group-by controls */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Gruppieren nach:</span>
        {[
          { value: 'none', label: 'Keine' },
          { value: 'unit', label: 'Einheit' },
          { value: 'status', label: 'Status' },
        ].map(opt => (
          <button
            key={opt.value}
            className={`btn btn-sm ${groupBy === opt.value ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setGroupBy(opt.value)}
            style={{ fontSize: '0.8rem', padding: '4px 10px' }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Lead tables */}
      {grouped.map((group, gi) => (
        <div key={gi} style={{ marginBottom: group.label ? '2rem' : 0 }}>
          {group.label && (
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1.1rem', borderBottom: '2px solid var(--primary)', paddingBottom: '0.25rem' }}>
              {group.label} ({group.leads.length})
            </h3>
          )}
          <DataTable
            title={group.label ? '' : 'Interessenten'}
            columns={COLUMNS}
            data={group.leads}
            onAdd={gi === 0 ? () => setModal('create') : undefined}
            onEdit={row => setModal(row)}
            onDelete={handleDelete}
          />
        </div>
      ))}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Interessent erstellen' : 'Interessent bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
