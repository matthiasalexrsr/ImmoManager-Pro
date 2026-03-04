import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';

const METER_COLUMNS = [
  { key: 'meter_number', label: 'Zählernr.', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'meter_type', label: 'Typ', filterType: 'select' },
  { key: 'installation_date', label: 'Einbaudatum', type: 'date' },
  { key: 'last_reading_value', label: 'Letzter Stand', type: 'number', align: 'right' },
  { key: 'last_reading_date', label: 'Letzte Ablesung', type: 'date' },
];

const READING_COLUMNS = [
  { key: 'reading_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'value', label: 'Zählerstand', type: 'number', align: 'right' },
  { key: 'consumption', label: 'Verbrauch', type: 'number', align: 'right',
    render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'recorded_by', label: 'Erfasst von', filterType: 'text' },
];

export default function Meters() {
  const [meters, setMeters] = useState([]);
  const [readings, setReadings] = useState([]);
  const [, setUnits] = useState([]);
  const [selectedMeter, setSelectedMeter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const loadData = () => {
    Promise.all([
      api.get('/meter-readings?type=meters').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([m, u]) => {
      setUnits(u);
      const unitMap = Object.fromEntries(u.map(x => [x.id, x]));
      // meter-readings endpoint returns readings; group by meter
      const meterMap = {};
      (Array.isArray(m) ? m : []).forEach(r => {
        if (!meterMap[r.meter_id]) {
          meterMap[r.meter_id] = {
            id: r.meter_id,
            meter_number: r.meter_id.slice(0, 8),
            unit_id: r.unit_id || '',
            meter_type: r.meter_type || '—',
            unit_label: r.unit_id ? (unitMap[r.unit_id]?.label || r.unit_id) : '—',
            readings: [],
          };
        }
        meterMap[r.meter_id].readings.push(r);
      });
      // Compute last reading per meter
      const meterList = Object.values(meterMap).map(meter => {
        const sorted = meter.readings.sort((a, b) =>
          (b.reading_date || '').localeCompare(a.reading_date || '')
        );
        return {
          ...meter,
          last_reading_value: sorted[0]?.value ?? '—',
          last_reading_date: sorted[0]?.reading_date ?? '—',
        };
      });
      setMeters(meterList);
    }).catch(err => console.warn('[Meters] load failed:', err.message)).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleSelectMeter = (meter) => {
    setSelectedMeter(meter);
    // Load readings for this meter
    api.get(`/meter-readings?meter_id=${meter.id}`).then(r => {
      const sorted = (Array.isArray(r) ? r : []).sort((a, b) =>
        (a.reading_date || '').localeCompare(b.reading_date || '')
      );
      // Calculate consumption between readings
      const withConsumption = sorted.map((rd, i) => ({
        ...rd,
        consumption: i > 0 ? rd.value - sorted[i - 1].value : null,
      }));
      setReadings(withConsumption);
    }).catch(() => setReadings([]));
  };

  const readingFields = [
    { key: 'meter_id', label: 'Zähler', type: 'select', required: true,
      options: meters.map(m => ({ value: m.id, label: `${m.meter_number} (${m.meter_type})` })) },
    { key: 'reading_date', label: 'Ablesedatum', type: 'date', required: true },
    { key: 'value', label: 'Zählerstand', type: 'number', required: true },
    { key: 'recorded_by', label: 'Erfasst von' },
  ];

  const handleSaveReading = async (data) => {
    await api.post('/meter-readings', data);
    loadData();
    if (selectedMeter) handleSelectMeter(selectedMeter);
  };

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
      <DataTable
        title="Zähler"
        columns={METER_COLUMNS}
        data={meters}
        onEdit={handleSelectMeter}
        onAdd={() => setModal('create')}
      />
      {selectedMeter && (
        <div style={{ marginTop: '1.5rem' }}>
          <DataTable
            title={`Ablesungen — ${selectedMeter.meter_number} (${selectedMeter.meter_type})`}
            columns={READING_COLUMNS}
            data={readings}
            onAdd={() => setModal('create')}
          />
        </div>
      )}
      {modal && (
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
