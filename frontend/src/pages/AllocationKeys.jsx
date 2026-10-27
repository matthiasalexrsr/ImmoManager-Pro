import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';

const KEY_TYPE_OPTIONS = [
  { value: 'area_sqm', label: 'Fläche (m²)' },
  { value: 'unit_count', label: 'Anzahl Einheiten' },
  { value: 'person_count', label: 'Personenzahl' },
  { value: 'consumption', label: 'Verbrauch' },
];

const KEY_TYPE_LABELS = Object.fromEntries(KEY_TYPE_OPTIONS.map(o => [o.value, o.label]));

// Consumption keys must say which meters count: water m³ and heat units do not add up.
const METER_TYPE_OPTIONS = [
  { value: 'cold_water', label: 'Kaltwasser' },
  { value: 'hot_water', label: 'Warmwasser' },
  { value: 'heating', label: 'Heizung' },
  { value: 'electricity', label: 'Strom' },
  { value: 'gas', label: 'Gas' },
];

const METER_TYPE_LABELS = Object.fromEntries(METER_TYPE_OPTIONS.map(o => [o.value, o.label]));

// The unit a consumption key bills in; meters in another unit are converted only by an exact factor.
const MEASURE_UNIT_OPTIONS = ['m³', 'l', 'kWh', 'MWh', 'Wh', 'HKV'].map(value => ({ value, label: value }));

const COLUMNS = [
  { key: 'name', label: 'Bezeichnung', filterType: 'text' },
  { key: 'key_type', label: 'Schlüsseltyp',
    render: (v, row) => (v === 'consumption' && row.meter_type
      ? `${KEY_TYPE_LABELS[v]} (${METER_TYPE_LABELS[row.meter_type] || row.meter_type}${row.measure_unit ? `, ${row.measure_unit}` : ''})`
      : (KEY_TYPE_LABELS[v] || v)) },
  { key: 'property_label', label: 'Immobilie', link: 'property' },
  { key: 'description', label: 'Beschreibung' },
];

export default function AllocationKeys() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const propertyState = useEntities('properties', '/properties');
  const properties = propertyState.items;
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const choicesReady = !propertyState.loading && !propertyState.error;

  const refreshData = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const request = new AbortController(); setLoading(true);
    api.list('/billing/allocation-keys', { signal: request.signal }).then(data => {
      if (request.signal.aborted) return;
      if (!Array.isArray(data)) throw new Error('Verteilerschlüssel konnten nicht vollständig gelesen werden.');
      setKeys(data); setLoaded(true); setError(null);
    }).catch(failure => { if (!request.signal.aborted) setError(failure.message || 'Verteilerschlüssel konnten nicht geladen werden.'); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [revision]);

  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const enriched = keys.map(k => ({ ...k, property_label: propertyMap[k.property_id] || '—' }));

  const fields = [
    { key: 'name', label: 'Bezeichnung', required: true, placeholder: 'z.B. Fläche Heizung' },
    { key: 'property_id', label: 'Immobilie', type: 'select', required: true,
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'key_type', label: 'Schlüsseltyp', type: 'select', required: true, options: KEY_TYPE_OPTIONS },
    { key: 'meter_type', label: 'Zählerart (nur bei Verbrauch)', type: 'select', options: METER_TYPE_OPTIONS },
    { key: 'measure_unit', label: t('pages.allocationKeys.measureUnit'), type: 'select', options: MEASURE_UNIT_OPTIONS,
      hint: t('pages.allocationKeys.measureUnitHint') },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (!choicesReady) throw new Error('Bitte zuerst die Immobilienauswahl erneut laden.');
    if (modal === 'create') {
      await api.post('/billing/allocation-keys', data);
    } else {
      await api.put(`/billing/allocation-keys/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('allocation_keys');
  };

  const handleDelete = async (row) => {
    const name = row.name || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
    setDeleteError(null);
    try {
      await api.del(`/billing/allocation-keys/${row.id}`);
      refreshData();
      if (store) store.invalidateRelated('allocation_keys');
    } catch (err) {
      setDeleteError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  if (loading && !loaded && !modal) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (error && !loaded && !modal) return <div className="page"><p className="alert-error" role="alert">{error}{' '}
    <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p></div>;

  return (
    <div className="page">
      {error && <p className="alert-error" role="alert">Verteilerschlüssel konnten nicht aktualisiert werden. {error} Angezeigt wird der zuletzt geladene Stand.{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={refreshData}>Erneut laden</button></p>}
      {propertyState.error && <p className="alert-error" role="alert">Die Immobilienauswahl ist nicht verfügbar. {propertyState.error}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={propertyState.reload}>Auswahl erneut laden</button></p>}
      {deleteError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {deleteError}
          <button onClick={() => setDeleteError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}
      <DataTable
        title="Verteilerschlüssel"
        columns={COLUMNS}
        data={enriched}
        onAdd={choicesReady ? () => setModal('create') : undefined}
        onEdit={choicesReady ? row => setModal(row) : undefined}
        onDelete={handleDelete}
      />
      {modal && (
        <FormModal
          title={modal === 'create' ? 'Verteilerschlüssel erstellen' : 'Verteilerschlüssel bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
