import useWriteAccess from '../hooks/useWriteAccess';
import { revisionOptions } from '../editRevision';
import { useState, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useFinanceData } from '../hooks/useFinanceData';
import FinanceLoadState from '../components/FinanceLoadState';
import { useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const METER_TYPE_LABELS = {
  cold_water: 'Kaltwasser',
  hot_water: 'Warmwasser',
  heating: 'Heizung',
  electricity: 'Strom',
  gas: 'Gas',
};

const METER_COLUMNS = [
  { key: 'serial_number', label: 'Seriennr.', filterType: 'text' },
  { key: 'property_name', label: 'Immobilie', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'meter_type', label: 'Typ', filterType: 'select',
    render: v => METER_TYPE_LABELS[v] || v },
  { key: 'location', label: 'Standort' },
  { key: 'supplier', label: 'Versorger', filterType: 'text' },
  { key: 'installation_date', label: 'Einbaudatum', type: 'date' },
  { key: 'next_inspection', label: 'Nächste Prüfung', type: 'date',
    render: (v) => {
      if (!v || v === '—') return '—';
      const d = new Date(v);
      const now = new Date();
      const diffDays = Math.ceil((d - now) / (1000 * 60 * 60 * 24));
      const color = diffDays < 0 ? 'var(--danger)' : diffDays < 30 ? 'var(--warning)' : 'inherit';
      return <span style={{ color, fontWeight: diffDays < 30 ? 600 : 'normal' }}>{v}</span>;
    }},
  { key: 'last_reading_value', label: 'Letzter Stand', type: 'number', align: 'right',
    render: v => v != null && v !== '—' ? Number(v).toFixed(2) : '—' },
  { key: 'last_reading_date', label: 'Letzte Ablesung', type: 'date' },
  { key: 'is_active', label: 'Status',
    render: v => v === false ? <StatusBadge status="inactive" /> : <StatusBadge status="active" /> },
];

const READING_COLUMNS = [
  { key: 'reading_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'value', label: 'Zählerstand', type: 'number', align: 'right',
    render: v => v != null ? Number(v).toFixed(2) : '—' },
  { key: 'consumption', label: 'Verbrauch', type: 'number', align: 'right',
    render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'recorded_by', label: 'Erfasst von', filterType: 'text' },
  { key: 'notes', label: 'Notizen' },
];

export default function Meters() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const [selectedMeterId, setSelectedMeterId] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/meters', () => setModal(null));
  const [groupBy, setGroupBy] = useState('none'); // 'none' | 'property' | 'type' | 'supplier'

  const { data: { rawMeters, allReadings, units, properties }, loading, error, reload: refreshData } = useFinanceData({
    rawMeters: '/meters', allReadings: '/meters/readings/all', units: '/units', properties: '/properties',
  });
  const readingsByMeter = useMemo(() => {
    const grouped = new Map();
    const ordered = [...allReadings].sort((a, b) => (a.reading_date || '').localeCompare(b.reading_date || ''));
    for (const reading of ordered) {
      if (!grouped.has(reading.meter_id)) grouped.set(reading.meter_id, []);
      grouped.get(reading.meter_id).push(reading);
    }
    return grouped;
  }, [allReadings]);
  const meters = useMemo(() => {
    const unitMap = Object.fromEntries(units.map(unit => [unit.id, unit]));
    const propertyMap = Object.fromEntries(properties.map(property => [property.id, property]));
    return rawMeters.map(meter => {
      const unit = unitMap[meter.unit_id];
      const latest = readingsByMeter.get(meter.id)?.at(-1);
      return { ...meter, unit_label: unit?.label || meter.unit_id || '—',
        property_name: propertyMap[unit?.property_id]?.name || '—', property_id: unit?.property_id || null,
        last_reading_value: latest?.value ?? '—', last_reading_date: latest?.reading_date ?? '—' };
    });
  }, [rawMeters, units, properties, readingsByMeter]);
  const selectedMeter = meters.find(meter => meter.id === selectedMeterId) || null;
  const readings = (readingsByMeter.get(selectedMeterId) || []).map((reading, index, rows) => ({
    ...reading, consumption: index > 0 ? Number(reading.value) - Number(rows[index - 1].value) : null,
  }));
  const handleSelectMeter = meter => setSelectedMeterId(meter.id);

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
    { key: 'serial_number', label: 'Seriennummer' },
    { key: 'location', label: 'Standort' },
    { key: 'installation_date', label: 'Einbaudatum', type: 'date' },
    { key: 'next_inspection', label: 'Nächste Prüfung', type: 'date' },
    { key: 'supplier', label: 'Versorger' },
    { key: 'contract_number', label: 'Vertragsnummer' },
    { key: 'contract_end_date', label: 'Vertragslaufzeit bis', type: 'date' },
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
    requireWrite();
    if (modal === 'create-meter') {
      await api.post('/meters', data);
    } else if (modal && modal.id) {
      await api.put(`/meters/${modal.id}`, data);
    }
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('meters', 'units');
  };

  const handleSaveReading = async (data) => {
    requireWrite();
    const meterId = data.meter_id;
    await api.post(`/meters/${meterId}/readings`, data);
    setModal(null);
    refreshData();
    if (store) store.invalidateRelated('meters', 'units');
  };

  const handleDeleteMeter = async (row) => {
    if (!isAllowed()) return;
    if (!await confirm(`"${row.serial_number || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    setActionError(null);
    try {
      if (!isAllowed()) return;
      await api.del(`/meters/${row.id}`, revisionOptions(row));
      if (selectedMeter?.id === row.id) {
        setSelectedMeterId(null);
      }
      setModal(null);
      refreshData();
      if (store) store.invalidateRelated('meters', 'units');
    } catch (err) {
      setActionError(err.message);
    }
  };

  // Group meters
  const getGroupedMeters = () => {
    if (groupBy === 'none') return [{ label: null, meters }];

    const groups = {};
    meters.forEach(m => {
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
    dueInspection: meters.filter(m => {
      if (!m.next_inspection) return false;
      const d = new Date(m.next_inspection);
      const now = new Date();
      return Math.ceil((d - now) / (1000 * 60 * 60 * 24)) < 30;
    }).length,
    types: Object.entries(
      meters.reduce((acc, m) => { acc[m.meter_type] = (acc[m.meter_type] || 0) + 1; return acc; }, {})
    ),
  };

  if (loading || error) return <FinanceLoadState loading={loading} error={error} onRetry={refreshData} />;

  const grouped = getGroupedMeters();

  return (
    <div className="page">
      {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}
      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '1rem', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary)' }}>{stats.total}</div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Zähler gesamt</div>
        </div>
        <div className="panel" style={{ padding: '1rem', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--success)' }}>{stats.active}</div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Aktiv</div>
        </div>
        <div className="panel" style={{ padding: '1rem', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: stats.dueInspection > 0 ? 'var(--warning)' : 'var(--text-secondary)' }}>{stats.dueInspection}</div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Prüfung fällig</div>
        </div>
        {stats.types.map(([type, count]) => (
          <div key={type} className="panel" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{count}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{METER_TYPE_LABELS[type] || type}</div>
          </div>
        ))}
      </div>

      {/* Group-by controls */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Gruppieren nach:</span>
        {[
          { value: 'none', label: 'Keine' },
          { value: 'property', label: 'Immobilie' },
          { value: 'type', label: 'Zählertyp' },
          { value: 'supplier', label: 'Versorger' },
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

      {/* Meter tables per group */}
      {grouped.map((group, gi) => (
        <div key={gi} style={{ marginBottom: group.label ? '2rem' : 0 }}>
          {group.label && (
            <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1.1rem', borderBottom: '2px solid var(--primary)', paddingBottom: '0.25rem' }}>
              {group.label} ({group.meters.length})
            </h3>
          )}
          <DataTable
            title={group.label ? '' : 'Zähler'}
            columns={METER_COLUMNS}
            data={group.meters}
            onEdit={canWrite ? handleSelectMeter : undefined}
            onRowClick={handleSelectMeter}
            onAdd={canWrite && gi === 0 ? () => setModal('create-meter') : undefined}
            onDelete={canWrite ? handleDeleteMeter : undefined}
          />
        </div>
      ))}

      {/* Selected meter readings */}
      {selectedMeter && (
        <div style={{ marginTop: '1.5rem' }}>
          <div className="panel" style={{ padding: '1rem', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ margin: 0 }}>
                  Ablesungen — {selectedMeter.serial_number || selectedMeter.id.slice(0, 8)} ({METER_TYPE_LABELS[selectedMeter.meter_type] || selectedMeter.meter_type})
                </h3>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  {selectedMeter.property_name !== '—' && <span>{selectedMeter.property_name} &rarr; </span>}
                  {selectedMeter.unit_label}
                  {selectedMeter.supplier && <span> | Versorger: {selectedMeter.supplier}</span>}
                  {selectedMeter.contract_number && <span> | Vertrag: {selectedMeter.contract_number}</span>}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {canWrite && <button className="btn btn-sm btn-primary" onClick={() => setModal('create-reading')}>
                  + Ablesung erfassen
                </button>}
                {canWrite && <button className="btn btn-sm btn-secondary" onClick={() => setModal(selectedMeter)}>
                  Zähler bearbeiten
                </button>}
                <button className="btn btn-sm btn-secondary" onClick={() => { setSelectedMeterId(null); }}>
                  Schließen
                </button>
              </div>
            </div>
          </div>
          <DataTable
            title=""
            columns={READING_COLUMNS}
            data={readings}
          />
        </div>
      )}

      {canWrite && modal === 'create-meter' && (
        <FormModal
          title="Zähler anlegen"
          fields={meterFields}
          initial={null}
          onSave={handleSaveMeter}
          onClose={() => setModal(null)}
        />
      )}
      {canWrite && modal && modal !== 'create-meter' && modal !== 'create-reading' && modal.id && (
        <FormModal
          title="Zähler bearbeiten"
          fields={meterFields}
          initial={modal}
          onSave={handleSaveMeter}
          onClose={() => setModal(null)}
        />
      )}
      {canWrite && modal === 'create-reading' && (
        <FormModal
          title="Ablesung erfassen"
          fields={readingFields}
          initial={selectedMeter ? { meter_id: selectedMeter.id } : null}
          onSave={handleSaveReading}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
