import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const STATUS_COLORS = {
  scheduled: 'var(--primary)',
  completed: 'var(--success)',
  cancelled: 'var(--text-secondary)',
  no_show: 'var(--danger)',
};

const TABLE_COLUMNS = [
  { key: 'lead_name', label: 'Interessent', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'scheduled_at', label: 'Termin', type: 'date', filterType: 'dateRange' },
  { key: 'agent', label: 'Betreuer', filterType: 'text' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

function MiniCalendar({ viewings, currentMonth, onMonthChange, onSelectDate, selectedDate }) {
  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDayOfWeek = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0

  // Build viewing count per day
  const viewingsByDay = useMemo(() => {
    const map = {};
    viewings.forEach(v => {
      if (!v.scheduled_at) return;
      const d = new Date(v.scheduled_at);
      if (d.getFullYear() === year && d.getMonth() === month) {
        const day = d.getDate();
        if (!map[day]) map[day] = [];
        map[day].push(v);
      }
    });
    return map;
  }, [viewings, year, month]);

  const weeks = [];
  let currentWeek = new Array(firstDayOfWeek).fill(null);

  for (let day = 1; day <= daysInMonth; day++) {
    currentWeek.push(day);
    if (currentWeek.length === 7) {
      weeks.push(currentWeek);
      currentWeek = [];
    }
  }
  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) currentWeek.push(null);
    weeks.push(currentWeek);
  }

  const today = new Date();
  const isToday = (day) => day && today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;

  const prevMonth = () => onMonthChange(new Date(year, month - 1, 1));
  const nextMonth = () => onMonthChange(new Date(year, month + 1, 1));

  const monthNames = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];

  return (
    <div className="panel" style={{ padding: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <button className="btn btn-sm btn-secondary" onClick={prevMonth}>&lsaquo;</button>
        <h3 style={{ margin: 0, fontSize: '1rem' }}>{monthNames[month]} {year}</h3>
        <button className="btn btn-sm btn-secondary" onClick={nextMonth}>&rsaquo;</button>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <thead>
          <tr>
            {['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map(d => (
              <th key={d} style={{ padding: '4px', textAlign: 'center', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week, wi) => (
            <tr key={wi}>
              {week.map((day, di) => {
                const dayViewings = day ? (viewingsByDay[day] || []) : [];
                const isSelected = selectedDate && day &&
                  selectedDate.getFullYear() === year && selectedDate.getMonth() === month && selectedDate.getDate() === day;
                return (
                  <td
                    key={di}
                    onClick={() => day && onSelectDate(new Date(year, month, day))}
                    style={{
                      padding: '4px 2px',
                      textAlign: 'center',
                      cursor: day ? 'pointer' : 'default',
                      borderRadius: '4px',
                      background: isSelected ? 'var(--primary)' : isToday(day) ? 'var(--bg-secondary, #f1f5f9)' : 'transparent',
                      color: isSelected ? '#fff' : day ? 'inherit' : 'transparent',
                      position: 'relative',
                      verticalAlign: 'top',
                      height: '36px',
                    }}
                  >
                    <div style={{ fontSize: '0.85rem', fontWeight: isToday(day) ? 700 : 'normal' }}>
                      {day || ''}
                    </div>
                    {dayViewings.length > 0 && (
                      <div style={{ display: 'flex', justifyContent: 'center', gap: '2px', marginTop: '1px' }}>
                        {dayViewings.slice(0, 3).map((v, vi) => (
                          <div
                            key={vi}
                            style={{
                              width: 6, height: 6, borderRadius: '50%',
                              background: STATUS_COLORS[v.status] || 'var(--primary)',
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Viewings() {
  const { t } = useTranslation();
  const store = useDataStore();
  const { items: leads } = useEntities('leads', '/leads');
  const { items: units } = useEntities('units', '/units');
  const [viewings, setViewings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [viewMode, setViewMode] = useState('calendar'); // 'calendar' | 'table'
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState(null);

  const refreshData = () => {
    setLoading(true);
    api.get('/viewings').catch(err => { console.warn('[Viewings]', err.message); return []; })
      .then(v => setViewings(v || []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/viewings').catch(err => { console.warn('[Viewings]', err.message); return []; })
      .then(data => { if (!cancelled) setViewings(data || []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const leadMap = Object.fromEntries(leads.map(l => [l.id, l]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const enriched = viewings.map(v => ({
    ...v,
    lead_name: leadMap[v.lead_id]?.full_name || '—',
    unit_label: unitMap[v.unit_id]?.label || '—',
    scheduled_at: v.scheduled_at?.slice(0, 16)?.replace('T', ' ') || '—',
    _raw_scheduled_at: v.scheduled_at,
  }));

  // Filter viewings for selected date
  const selectedDateViewings = useMemo(() => {
    if (!selectedDate) return [];
    return enriched.filter(v => {
      if (!v._raw_scheduled_at) return false;
      const d = new Date(v._raw_scheduled_at);
      return d.getFullYear() === selectedDate.getFullYear() &&
        d.getMonth() === selectedDate.getMonth() &&
        d.getDate() === selectedDate.getDate();
    });
  }, [enriched, selectedDate]);

  // Upcoming viewings (next 7 days)
  const upcomingViewings = useMemo(() => {
    const now = new Date();
    const weekLater = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
    return enriched
      .filter(v => {
        if (!v._raw_scheduled_at || v.status === 'cancelled') return false;
        const d = new Date(v._raw_scheduled_at);
        return d >= now && d <= weekLater;
      })
      .sort((a, b) => (a._raw_scheduled_at || '').localeCompare(b._raw_scheduled_at || ''));
  }, [enriched]);

  const fields = [
    { key: 'lead_id', label: 'Interessent', required: true, type: 'select',
      options: leads.map(l => ({ value: l.id, label: l.full_name })) },
    { key: 'unit_id', label: 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'scheduled_at', label: 'Termin', type: 'datetime-local', required: true },
    { key: 'agent', label: 'Betreuer' },
    { key: 'status', label: 'Status', type: 'select', default: 'scheduled', options: [
      { value: 'scheduled', label: 'Geplant' },
      { value: 'completed', label: 'Durchgeführt' },
      { value: 'cancelled', label: 'Abgesagt' },
      { value: 'no_show', label: 'Nicht erschienen' },
    ]},
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/viewings', data);
    } else {
      await api.put(`/viewings/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateAll();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`"${row.lead_name}" ${t('modals.confirmDelete.body')}`)) return;
    setDeleteError(null);
    try {
      await api.del(`/viewings/${row.id}`);
      refreshData();
      if (store) store.invalidateAll();
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  const statusLabels = { scheduled: 'Geplant', completed: 'Durchgeführt', cancelled: 'Abgesagt', no_show: 'Nicht erschienen' };

  return (
    <div className="page">
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* View mode toggle */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0 }}>Besichtigungen</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className={`btn btn-sm ${viewMode === 'calendar' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('calendar')}
          >
            Kalender
          </button>
          <button
            className={`btn btn-sm ${viewMode === 'table' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('table')}
          >
            Tabelle
          </button>
          <button className="btn btn-primary" onClick={() => setModal('create')}>
            + Besichtigung
          </button>
        </div>
      </div>

      {viewMode === 'calendar' ? (
        <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1.5rem' }}>
          {/* Calendar sidebar */}
          <div>
            <MiniCalendar
              viewings={viewings}
              currentMonth={currentMonth}
              onMonthChange={setCurrentMonth}
              onSelectDate={setSelectedDate}
              selectedDate={selectedDate}
            />

            {/* Legend */}
            <div className="panel" style={{ padding: '0.75rem', marginTop: '1rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem' }}>Legende</div>
              {Object.entries(STATUS_COLORS).map(([status, color]) => (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: color }} />
                  <span style={{ fontSize: '0.8rem' }}>{statusLabels[status] || status}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Day detail / Upcoming */}
          <div>
            {selectedDate ? (
              <div>
                <h3 style={{ margin: '0 0 1rem 0' }}>
                  {selectedDate.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
                </h3>
                {selectedDateViewings.length === 0 ? (
                  <p className="empty-text">Keine Besichtigungen an diesem Tag.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {selectedDateViewings.map(v => (
                      <div
                        key={v.id}
                        className="panel"
                        style={{
                          padding: '1rem',
                          borderLeft: `4px solid ${STATUS_COLORS[v.status] || 'var(--primary)'}`,
                          cursor: 'pointer',
                        }}
                        onClick={() => setModal(v)}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <div style={{ fontWeight: 600 }}>{v.lead_name}</div>
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                              {v.unit_label} &bull; {v.scheduled_at}
                            </div>
                            {v.agent && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>Betreuer: {v.agent}</div>}
                            {v.notes && <div style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>{v.notes}</div>}
                          </div>
                          <StatusBadge status={v.status} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div>
                <h3 style={{ margin: '0 0 1rem 0' }}>Nächste Termine (7 Tage)</h3>
                {upcomingViewings.length === 0 ? (
                  <p className="empty-text">Keine anstehenden Besichtigungen.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {upcomingViewings.map(v => (
                      <div
                        key={v.id}
                        className="panel"
                        style={{
                          padding: '1rem',
                          borderLeft: `4px solid ${STATUS_COLORS[v.status] || 'var(--primary)'}`,
                          cursor: 'pointer',
                        }}
                        onClick={() => setModal(v)}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <div style={{ fontWeight: 600 }}>{v.lead_name}</div>
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                              {v.unit_label} &bull; {v.scheduled_at}
                            </div>
                            {v.agent && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Betreuer: {v.agent}</div>}
                          </div>
                          <StatusBadge status={v.status} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <DataTable
          title=""
          columns={TABLE_COLUMNS}
          data={enriched}
          onAdd={() => setModal('create')}
          onEdit={row => setModal(row)}
          onDelete={handleDelete}
        />
      )}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Besichtigung erstellen' : 'Besichtigung bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
