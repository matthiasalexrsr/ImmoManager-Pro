import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const OWNER_COLORS = {
  'Richard': '#2563eb',
  'Sabine': '#16a34a',
  'Matthias': '#d97706',
  'Linda': '#8b5cf6',
};

const COLUMNS = [
  { key: 'name', label: 'Name', filterType: 'text' },
  { key: 'owner_name', label: 'Eigentümer', filterType: 'text',
    render: v => {
      const color = OWNER_COLORS[v] || 'var(--text-secondary)';
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
          <span style={{
            width: '10px', height: '10px', borderRadius: '50%',
            backgroundColor: color, display: 'inline-block', flexShrink: 0
          }} />
          {v || '—'}
        </span>
      );
    }},
  { key: 'property_count', label: 'Immobilien', type: 'number', align: 'right' },
  { key: 'total_units', label: 'Einheiten', type: 'number', align: 'right' },
  { key: 'currency', label: 'Währung' },
  { key: 'description', label: 'Beschreibung' },
  { key: 'status', label: 'Status', type: 'status', filterType: 'select',
    render: v => <StatusBadge status={v} /> },
];

const FIELDS = [
  { key: 'name', label: 'Name', required: true },
  { key: 'description', label: 'Beschreibung', type: 'textarea' },
  { key: 'owner_name', label: 'Eigentümer', type: 'select', options: [
    { value: '', label: '— Auswählen —' },
    { value: 'Richard', label: 'Richard' },
    { value: 'Sabine', label: 'Sabine' },
    { value: 'Matthias', label: 'Matthias' },
    { value: 'Linda', label: 'Linda' },
    { value: 'Andere', label: 'Andere' },
  ]},
  { key: 'currency', label: 'Währung', default: 'EUR', type: 'select', options: [
    { value: 'EUR', label: 'EUR (€)' },
    { value: 'CHF', label: 'CHF (Fr.)' },
    { value: 'USD', label: 'USD ($)' },
  ]},
  { key: 'timezone', label: 'Zeitzone', default: 'Europe/Berlin' },
  { key: 'status', label: 'Status', type: 'select', default: 'active', options: [
    { value: 'active', label: 'Aktiv' }, { value: 'inactive', label: 'Inaktiv' },
  ]},
];

export default function Portfolios() {
  const [portfolios, setPortfolios] = useState([]);
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      api.get('/portfolios').catch(() => []),
      api.get('/properties').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([p, props, u]) => {
      setPortfolios(Array.isArray(p) ? p : []);
      setProperties(Array.isArray(props) ? props : []);
      setUnits(Array.isArray(u) ? u : []);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  // Enrich portfolios with property & unit counts
  const enriched = portfolios.map(pf => {
    const pfProperties = properties.filter(p => p.portfolio_id === pf.id);
    const pfPropertyIds = new Set(pfProperties.map(p => p.id));
    const pfUnits = units.filter(u => pfPropertyIds.has(u.property_id));
    return {
      ...pf,
      property_count: pfProperties.length,
      total_units: pfUnits.length,
    };
  });

  // Summary by owner
  const ownerSummary = Object.entries(
    enriched.reduce((acc, pf) => {
      const owner = pf.owner_name || 'Unbekannt';
      if (!acc[owner]) acc[owner] = { count: 0, properties: 0, units: 0 };
      acc[owner].count++;
      acc[owner].properties += pf.property_count;
      acc[owner].units += pf.total_units;
      return acc;
    }, {})
  );

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/portfolios', data);
    } else {
      await api.put(`/portfolios/${modal.id}`, data);
    }
    loadData();
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`Portfolio "${row.name}" wirklich löschen?`)) return;
    await api.del(`/portfolios/${row.id}`);
    loadData();
  };

  if (loading) return <div className="page-loading">Lade Portfolios...</div>;

  return (
    <div className="page">
      <h1 className="page-title">Portfolios</h1>

      {/* Owner summary cards */}
      {ownerSummary.length > 0 && (
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
          {ownerSummary.map(([owner, data]) => (
            <div key={owner} className="panel" style={{
              padding: '0.75rem 1rem', minWidth: '160px',
              borderLeft: `4px solid ${OWNER_COLORS[owner] || 'var(--border-color)'}`,
            }}>
              <div style={{ fontWeight: 700, marginBottom: '0.25rem' }}>{owner}</div>
              <div className="text-muted" style={{ fontSize: '0.8rem' }}>
                {data.count} Portfolio{data.count !== 1 ? 's' : ''} · {data.properties} Immobilien · {data.units} Einheiten
              </div>
            </div>
          ))}
        </div>
      )}

      <DataTable
        title="Portfolios"
        columns={COLUMNS}
        data={enriched}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Portfolio erstellen' : 'Portfolio bearbeiten'}
          fields={FIELDS}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
