import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

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
  { key: 'currency', label: 'Währung', hidden: true },
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
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [portfolios, setPortfolios] = useState([]);
  const [properties, setProperties] = useState(null);
  const [units, setUnits] = useState(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [aggregateErrors, setAggregateErrors] = useState([]);
  const [revision, setRevision] = useState(0);

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController(); setLoading(true);
    Promise.allSettled(['/portfolios', '/properties', '/units'].map(path => api.list(path, { signal: request.signal })))
      .then(([portfolios, properties, units]) => {
      if (request.signal.aborted) return;
      if (portfolios.status === 'fulfilled' && Array.isArray(portfolios.value)) {
        setPortfolios(portfolios.value); setLoaded(true); setLoadError(null);
      } else setLoadError(portfolios.reason?.message || 'Portfolios konnten nicht vollständig gelesen werden.');
      const errors = [];
      if (properties.status === 'fulfilled' && Array.isArray(properties.value)) setProperties(properties.value);
      else errors.push('Immobilien: ' + (properties.reason?.message || 'Die Datenquelle konnte nicht vollständig gelesen werden.'));
      if (units.status === 'fulfilled' && Array.isArray(units.value)) setUnits(units.value);
      else errors.push('Einheiten: ' + (units.reason?.message || 'Die Datenquelle konnte nicht vollständig gelesen werden.'));
      setAggregateErrors(errors); setLoading(false);
    });
    return () => request.abort();
  }, [revision]);
  const countsReady = properties !== null && units !== null && !aggregateErrors.length && !loadError;

  // Enrich portfolios with property & unit counts
  const enriched = portfolios.map(pf => {
    const pfProperties = (properties || []).filter(p => p.portfolio_id === pf.id);
    const pfPropertyIds = new Set(pfProperties.map(p => p.id));
    const pfUnits = (units || []).filter(u => pfPropertyIds.has(u.property_id));
    return {
      ...pf,
      property_count: countsReady ? pfProperties.length : null,
      total_units: countsReady ? pfUnits.length : null,
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
    refreshData();
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.name}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    try {
      await api.del(`/portfolios/${row.id}`);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    refreshData();
  };

  // only the first load replaces the page; a reload keeps the table and an open form
  if (loading && !loaded && !modal) return <div className="page-loading">Lade Portfolios...</div>;
  if (loadError && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{loadError}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      <h1 className="page-title">Portfolios</h1>
      {loadError && <p className="alert-error" role="alert">Portfolios konnten nicht aktualisiert werden. {loadError} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {aggregateErrors.length > 0 && <p className="alert-error" role="alert">Die Anzahl der Immobilien und Einheiten ist derzeit unbekannt. {aggregateErrors.join(' · ')}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Bestandszahlen erneut laden</button></p>}

      {/* Owner summary cards */}
      {ownerSummary.length > 0 && (
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
          {ownerSummary.map(([owner, data]) => (
            <div key={owner} className="panel" style={{
              padding: '0.75rem 1rem', minWidth: '160px',
              borderLeft: `4px solid ${OWNER_COLORS[owner] || 'var(--border-color)'}`,
            }}>
              <div style={{ fontWeight: 700, marginBottom: '0.25rem' }}>{owner}</div>
              <div className="text-muted" style={{ fontSize: 'var(--text-xs)' }}>
                {data.count} Portfolio{data.count !== 1 ? 's' : ''} · {countsReady ? `${data.properties} Immobilien · ${data.units} Einheiten` : 'Immobilien und Einheiten unbekannt'}
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
