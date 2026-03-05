import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';

const METER_COLUMNS = [
  { key: 'serial_number', label: 'Seriennr.', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'meter_type', label: 'Typ', filterType: 'select',
    render: v => {
      const labels = { cold_water: 'Kaltwasser', hot_water: 'Warmwasser', heating: 'Heizung', electricity: 'Strom', gas: 'Gas' };
      return labels[v] || v;
    }},
  { key: 'location', label: 'Standort' },
  { key: 'supplier', label: 'Versorger', filterType: 'text' },
  { key: 'installation_date', label: 'Einbaudatum', type: 'date' },
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
  const [meters, setMeters] = useState([]);
  const [units, setUnits] = useState([]);
  const [selectedMeter, setSelectedMeter] = useState(null);
  const [readings, setReadings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // 'create-meter' | 'create-reading' | meter (edit)

  const loadData = () => {
    Promise.all([
      api.get('/meters').catch(() => []),
      api.get('/units').catch(() => []),
    ]).then(([m, u]) => {
      setUnits(u || []);
      const unitMap = Object.fromEntries((u || []).map(x => [x.id, x]));

      // Enrich meters with unit label and last reading
      const enriched = (m || []).map(meter => ({
        ...meter,
        unit_label: unitMap[meter.unit_id]?.label || meter.unit_id || '—',
        last_reading_value: '—',
        last_reading_date: '—',
      }));

      // Load all readings to compute last readings per meter
      api.get('/meters/readings/all').then(allReadings => {
        const readingsByMeter = {};
        (allReadings || []).forEach(r => {
          if (!readingsByMeter[r.meter_id]) readingsByMeter[r.meter_id] = [];
          readingsByMeter[r.meter_id].push(r);
        });

        enriched.forEach(meter => {
          const meterReadings = readingsByMeter[meter.id] || [];
          if (meterReadings.length > 0) {
            const sorted = meterReadings.sort((a, b) =>
              (b.reading_date || '').localeCompare(a.reading_date || '')
            );
            meter.last_reading_value = sorted[0].value;
            meter.last_reading_date = sorted[0].reading_date;
          }
        });

        setMeters([...enriched]);
      }).catch(() => setMeters(enriched));
    }).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleSelectMeter = (meter) => {
    setSelectedMeter(meter);
    api.get(`/meters/${meter.id}/readings`).then(r => {
      const sorted = (r || []).sort((a, b) =>
        (a.reading_date || '').localeCompare(b.reading_date || '')
      );
      const withConsumption = sorted.map((rd, i) => ({
        ...rd,
        consumption: i > 0 ? rd.value - sorted[i - 1].value : null,
      }));
      setReadings(withConsumption);
    }).catch(() => setReadings([]));
  };

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
  ];

  const readingFields = [
    { key: 'meter_id', label: 'Zähler', type: 'select', required: true,
      options: meters.map(m => ({ value: m.id, label: `${m.serial_number || m.id.slice(0, 8)} (${m.meter_type})` })) },
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
    loadData();
  };

  const handleSaveReading = async (data) => {
    const meterId = data.meter_id;
    await api.post(`/meters/${meterId}/readings`, data);
    loadData();
    if (selectedMeter) handleSelectMeter(selectedMeter);
  };

  const handleDeleteMeter = async (row) => {
    if (!window.confirm(`Zähler "${row.serial_number || row.id}" wirklich löschen?`)) return;
    await api.del(`/meters/${row.id}`);
    if (selectedMeter?.id === row.id) {
      setSelectedMeter(null);
      setReadings([]);
    }
    loadData();
  };

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
      <DataTable
        title="Zähler"
        columns={METER_COLUMNS}
        data={meters}
        onEdit={handleSelectMeter}
        onAdd={() => setModal('create-meter')}
        onDelete={handleDeleteMeter}
      />
      {selectedMeter && (
        <div style={{ marginTop: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <h3>Ablesungen — {selectedMeter.serial_number || selectedMeter.id.slice(0, 8)} ({
              { cold_water: 'Kaltwasser', hot_water: 'Warmwasser', heating: 'Heizung', electricity: 'Strom', gas: 'Gas' }[selectedMeter.meter_type] || selectedMeter.meter_type
            })</h3>
            <button className="btn btn-sm btn-primary" onClick={() => setModal('create-reading')}>
              + Ablesung erfassen
            </button>
          </div>
          <DataTable
            title=""
            columns={READING_COLUMNS}
            data={readings}
          />
        </div>
      )}

      {modal === 'create-meter' && (
        <FormModal
          title="Zähler anlegen"
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
