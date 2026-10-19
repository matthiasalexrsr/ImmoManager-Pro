import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { formatDate, formatNumber } from '../utils/format';
import KpiAction from '../components/KpiAction';
import MeterHistory from '../features/meters/MeterHistory';
import { useCanWrite } from '../contexts/AuthContext';

const METER_TYPE_LABELS = {
  cold_water: 'Kaltwasser',
  hot_water: 'Warmwasser',
  heating: 'Heizung',
  electricity: 'Strom',
  gas: 'Gas',
};

// Units the utility statement converts only by an exact factor (MWh -> kWh, l -> m³).
const MEASURE_UNITS = ['m³', 'l', 'kWh', 'MWh', 'Wh', 'HKV'].map(value => ({ value, label: value }));

// The meter number opens its history (readings, consumption per year, supply contract and portal).
const meterColumns = onOpen => [
  { key: 'serial_number', label: 'Seriennr.', filterType: 'text',
    render: (v, row) => <button type="button" className="entity-link link-button" title="Zählerverlauf öffnen"
      onClick={event => { event.stopPropagation(); onOpen(row); }}>{v || row.id.slice(0, 8)}</button> },
  { key: 'property_name', hidden: true, label: 'Immobilie', filterType: 'text' },
  { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text', link: 'unit', subLink: 'property' },
  { key: 'meter_type', label: 'Typ', filterType: 'select',
    render: v => METER_TYPE_LABELS[v] || v },
  { key: 'location', hidden: true, label: 'Standort' },
  { key: 'supplier', hidden: true, label: 'Versorger', filterType: 'text', link: 'contact' },
  { key: 'measure_unit', hidden: true, label: 'Einheit der Ablesung' },
  { key: 'installation_date', hidden: true, label: 'Einbaudatum', type: 'date' },
  { key: 'removal_date', hidden: true, label: 'Ausbaudatum', type: 'date' },
  { key: 'next_inspection', label: 'Nächste Prüfung', type: 'date',
    render: (v) => {
      if (!v || v === '—') return '—';
      const d = new Date(v);
      const now = new Date();
      const diffDays = Math.ceil((d - now) / (1000 * 60 * 60 * 24));
      const color = diffDays < 0 ? 'var(--danger)' : diffDays < 30 ? 'var(--warning)' : 'inherit';
      return <span style={{ color, fontWeight: diffDays < 30 ? 600 : 'normal' }}>{formatDate(v)}</span>;
    }},
  { key: 'last_reading_value', label: 'Letzter Stand', type: 'number', align: 'right',
    render: v => v !== '—' ? formatNumber(v, 2) : '—' },
  { key: 'last_reading_date', label: 'Letzte Ablesung', type: 'date' },
  { key: 'is_active', label: 'Status',
    render: v => v === false ? <StatusBadge status="inactive" /> : <StatusBadge status="active" /> },
];

export default function Meters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: units } = useEntities('units', '/units');
  const { items: properties } = useEntities('properties', '/properties');
  const [meters, setMeters] = useState([]);
  const focusedMeter = searchParams.get('focus_id');
  const previousFocus = useRef(focusedMeter);
  const [historyOf, setHistoryOf] = useState(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const canWrite = useCanWrite('/meters');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [groupBy, setGroupBy] = useState('none'); // 'none' | 'property' | 'type' | 'supplier'

  const [loadError, setLoadError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [sourceFilter, setSourceFilter] = useState('all');
  const [drilldown, setDrilldown] = useState(0);
  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  const openSources = value => { setSearchParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('suche'); return next; }); setSourceFilter(value); setGroupBy('none'); setHistoryOf(null); setDrilldown(number => number + 1); };
  const inspectionSoon = meter => meter.next_inspection && Math.ceil((new Date(meter.next_inspection) - new Date()) / 86400000) < 30;
  const visibleMeters = meters.filter(meter => focusedMeter || sourceFilter === 'all' || (sourceFilter === 'active' ? meter.is_active !== false
    : sourceFilter === 'inspection' ? inspectionSoon(meter) : meter.meter_type === sourceFilter.slice(5)));

  useEffect(() => {
    const request = new AbortController(); setLoading(true); setLoadError(null);
    Promise.allSettled(['/meters', '/meters/readings/all'].map(path => api.list(path, { signal: request.signal }))).then(([result, readingResult]) => {
      if (request.signal.aborted) return;
      const failures = [];
      if (result.status !== 'fulfilled' || !Array.isArray(result.value)) {
        setLoadError(result.reason?.message || 'Die Zähler konnten nicht gelesen werden.'); return;
      }
      const unitMap = Object.fromEntries(units.map(row => [row.id, row]));
      const propMap = Object.fromEntries(properties.map(row => [row.id, row]));
      const latest = new Map();
      if (readingResult.status === 'fulfilled' && Array.isArray(readingResult.value)) {
        readingResult.value.forEach(reading => {
          if (!latest.has(reading.meter_id) || reading.reading_date > latest.get(reading.meter_id).reading_date) latest.set(reading.meter_id, reading);
        });
      } else failures.push(readingResult.reason?.message || 'Die Ablesungen konnten nicht gelesen werden.');
      setMeters(result.value.map(meter => { const unit = unitMap[meter.unit_id]; const reading = latest.get(meter.id);
        return { ...meter, unit_label: unit?.label || meter.unit_id || '—', property_id: unit?.property_id || null,
          property_name: propMap[unit?.property_id]?.name || '—', last_reading_value: reading?.value ?? '—', last_reading_date: reading?.reading_date || '—' };
      }));
      if (failures.length) setLoadError(failures.join(' · '));
    }).finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision, units, properties]);

  const noticeMeter = focusedMeter;
  useEffect(() => {
    // Back to an ordinary list must leave the URL-opened history. A manually
    // opened history has no URL focus and remains open during a data refresh.
    if (previousFocus.current && !focusedMeter) setHistoryOf(null);
    previousFocus.current = focusedMeter;
  }, [focusedMeter]);
  useEffect(() => {
    if (noticeMeter && !loading && historyOf?.id !== noticeMeter) {
      const meter = meters.find(row => row.id === noticeMeter); if (meter) setHistoryOf(meter);
    }
  // The source changes only with the loaded meter set or navigation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noticeMeter, loading, meters]);

  const meterFields = [
    { key: 'unit_id', label: 'Einheit', type: 'select', required: true,
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'meter_type', label: 'Typ', type: 'select', required: true, options: [
      { value: 'cold_water', label: 'Kaltwasser' },
      { value: 'hot_water', label: 'Warmwasser' },
      { value: 'heating', label: 'Heizung' },
      { value: 'electricity', label: 'Strom' },
      { value: 'gas', label: 'Gas' },
    ]},
    { key: 'measure_unit', label: t('pages.meters.measureUnit'), type: 'select', options: MEASURE_UNITS,
      hint: t('pages.meters.measureUnitHint') },
    { key: 'serial_number', label: 'Seriennummer' },
    { key: 'location', label: 'Standort' },
    { key: 'installation_date', label: 'Einbaudatum', type: 'date', hint: t('pages.meters.installationDateHint') },
    { key: 'removal_date', label: t('pages.meters.removalDate'), type: 'date', hint: t('pages.meters.removalDateHint') },
    { key: 'next_inspection', label: 'Nächste Prüfung', type: 'date' },
    { key: 'supplier', label: 'Versorger' },
    { key: 'contract_number', label: 'Vertragsnummer' },
    { key: 'contract_end_date', label: 'Vertragslaufzeit bis', type: 'date' },
    { key: 'portal_url', label: 'Kundenportal (Link)', placeholder: 'https://kundenportal.anbieter.de',
      hint: 'Die Anmeldeseite des Versorgers zu diesem Zähler; im Zählerverlauf als Link.' },
  ];

  const readingFields = [
    { key: 'meter_id', label: 'Zähler', type: 'select', required: true,
      options: meters.map(m => ({ value: m.id, label: `${m.serial_number || m.id.slice(0, 8)} (${METER_TYPE_LABELS[m.meter_type] || m.meter_type})` })) },
    { key: 'reading_date', label: 'Ablesedatum', type: 'date', required: true },
    { key: 'value', label: 'Zählerstand', type: 'number', required: true },
    { key: 'recorded_by', label: 'Erfasst von' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSaveMeter = async (data) => {
    if (modal === 'create-meter') {
      await api.post('/meters', data);
    } else if (modal && modal.id) {
      await api.put(`/meters/${modal.id}`, data);
    }
    refreshData();
    setHistoryRevision(value => value + 1);
    if (store) store.invalidateRelated('meters', 'units');
  };

  const handleSaveReading = async (data) => {
    const meterId = data.meter_id;
    await api.post(`/meters/${meterId}/readings`, data);
    refreshData();
    setHistoryRevision(value => value + 1);
    if (store) store.invalidateRelated('meters', 'units');
  };

  const handleDeleteMeter = async (row) => {
    if (!await confirm(`"${row.serial_number || row.id}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    await api.del(`/meters/${row.id}`);
    if (historyOf?.id === row.id) setHistoryOf(null);
    refreshData();
    if (store) store.invalidateRelated('meters', 'units');
  };

  // Group meters
  const getGroupedMeters = () => {
    if (focusedMeter || groupBy === 'none' || !visibleMeters.length) return [{ label: null, meters: visibleMeters }];

    const groups = {};
    visibleMeters.forEach(m => {
      let key;
      if (groupBy === 'property') key = m.property_name || 'Ohne Immobilie';
      else if (groupBy === 'type') key = METER_TYPE_LABELS[m.meter_type] || m.meter_type || 'Unbekannt';
      else if (groupBy === 'supplier') key = m.supplier || 'Kein Versorger';
      if (!groups[key]) groups[key] = [];
      groups[key].push(m);
    });

    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, meters]) => ({ label, meters }));
  };

  // Summary stats
  const stats = {
    total: meters.length,
    active: meters.filter(m => m.is_active !== false).length,
    dueInspection: meters.filter(inspectionSoon).length,
    types: Object.entries(
      meters.reduce((acc, m) => { acc[m.meter_type] = (acc[m.meter_type] || 0) + 1; return acc; }, {})
    ),
  };

  if (loading && !modal) return <div className="page-loading">Laden...</div>;

  const grouped = getGroupedMeters();

  return (
    <div className="page">
      {loadError && <p role="alert">{loadError} <button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></p>}
      {!focusedMeter && sourceFilter === 'inspection' && <p className="text-muted">Prüftermine in weniger als 30 Tagen, einschließlich überfälliger Termine und inaktiver Zähler.</p>}
      {/* Summary Cards */}
      <div className="kpi-row">
        <KpiAction label="Zähler gesamt" value={loadError && !meters.length ? '—' : stats.total} onClick={() => openSources('all')} />
        <KpiAction label="Aktiv" value={loadError && !meters.length ? '—' : stats.active} color="var(--success)" onClick={() => openSources('active')} />
        <KpiAction label="Prüfung fällig" value={loadError && !meters.length ? '—' : stats.dueInspection} color={stats.dueInspection ? 'var(--warning)' : undefined} onClick={() => openSources('inspection')} />
        {stats.types.map(([type, count]) => <KpiAction key={type} label={METER_TYPE_LABELS[type] || type} value={count} onClick={() => openSources(`type:${type}`)} />)}
      </div>

      {/* Group-by controls */}
      <div className="toolbar">
        <span className="toolbar-label">Gruppieren nach:</span>
        {[
          { value: 'none', label: 'Keine' },
          { value: 'property', label: 'Immobilie' },
          { value: 'type', label: 'Zählertyp' },
          { value: 'supplier', label: 'Versorger' },
        ].map(opt => (
          <button
            key={opt.value}
            className={`btn btn-sm ${(focusedMeter ? 'none' : groupBy) === opt.value ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setGroupBy(opt.value)}
            style={{ fontSize: 'var(--text-xs)', padding: '4px 10px' }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Meter tables per group */}
      {grouped.map((group, gi) => (
        <div key={gi} style={{ marginBottom: group.label ? '2rem' : 0 }}>
          {group.label && (
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: 'var(--text-lg)', borderBottom: '2px solid var(--primary)', paddingBottom: '0.25rem' }}>
              {group.label} ({group.meters.length})
            </h3>
          )}
          <DataTable
            title={group.label ? '' : 'Zähler'}
            columns={meterColumns(setHistoryOf)}
            data={group.meters}
            drilldownKey={drilldown}
            emptyText={loadError && !meters.length ? 'Zähler noch nicht verfügbar.' : undefined}
            viewConfig={{ column_filters: { meter_filter: sourceFilter } }}
            onApplyView={config => setSourceFilter(config.column_filters?.meter_filter || 'all')}
            onEdit={row => setModal(row)}
            rowActions={row => [{ label: 'Verlauf', onClick: () => setHistoryOf(row) }]}
            onAdd={gi === 0 ? () => setModal('create-meter') : undefined}
            onDelete={handleDeleteMeter}
          />
        </div>
      ))}

      {historyOf && (
        <MeterHistory meterId={historyOf.id} meterLabel={historyOf.serial_number || historyOf.id.slice(0, 8)}
          unitLabel={historyOf.unit_label !== '—' ? historyOf.unit_label : null}
          propertyName={historyOf.property_name !== '—' ? historyOf.property_name : null} propertyId={historyOf.property_id}
          revision={historyRevision} covered={Boolean(modal)} canWrite={canWrite}
          onClose={() => setHistoryOf(null)} onRecord={() => setModal('create-reading')}
          onEdit={() => setModal(meters.find(row => row.id === historyOf.id) || historyOf)} />
      )}

      {modal === 'create-meter' && (
        <FormModal
          title="Zähler anlegen"
          repeatKeep={['unit_id', 'meter_type', 'measure_unit', 'installation_date']}
          fields={meterFields}
          initial={null}
          onSave={handleSaveMeter}
          onClose={() => setModal(null)}
        />
      )}
      {modal && modal !== 'create-meter' && modal !== 'create-reading' && modal.id && (
        <FormModal
          title="Zähler bearbeiten"
          fields={meterFields}
          initial={modal}
          onSave={handleSaveMeter}
          onClose={() => setModal(null)}
        />
      )}
      {modal === 'create-reading' && (
        <FormModal
          draftContext="readings"
          draftAnchor={historyOf ? { kind: 'meter', id: historyOf.id } : undefined}
          title="Ablesung erfassen"
          repeatKeep={['reading_date', 'recorded_by']}
          fields={readingFields}
          initial={historyOf ? { meter_id: historyOf.id } : null}
          onSave={handleSaveReading}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
