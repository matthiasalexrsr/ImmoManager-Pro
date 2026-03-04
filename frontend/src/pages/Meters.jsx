import { useState, useEffect } from 'react';
import { api } from '../api';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';

const METER_COLUMNS = [
  { key: 'meter_number', label: 'Zählernr.', filterType: 'text' },
  { key: 'unit_label', label: 'Einheit', filterType: 'text' },
  { key: 'meter_type', label: 'Typ', filterType: 'select' },
  { key: 'unit_display', label: 'Messeinheit' },
  { key: 'last_reading_value', label: 'Letzter Stand', type: 'number', align: 'right' },
  { key: 'last_reading_date', label: 'Letzte Ablesung', type: 'date' },
];

const READING_COLUMNS = [
  { key: 'reading_date', label: 'Datum', type: 'date', filterType: 'dateRange' },
  { key: 'reading_value', label: 'Zählerstand', type: 'number', align: 'right' },
  { key: 'consumption', label: 'Verbrauch', type: 'number', align: 'right',
    render: v => v != null ? v.toFixed(2) : '—' },
  { key: 'unit', label: 'Einheit' },
  { key: 'notes', label: 'Notizen' },
];

export default function Meters() {
  const [meters, setMeters] = useState([]);
  const [readings, setReadings] = useState([]);
  const [units, setUnits] = useState([]);
  const [protocols, setProtocols] = useState([]);
  const [selectedMeter, setSelectedMeter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  const loadData = () => {
    Promise.all([
      api.get('/handover-protocols/meter-readings').catch(err => { console.warn('[Meters] readings:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Meters] units:', err.message); return []; }),
      api.get('/handover-protocols').catch(err => { console.warn('[Meters] protocols:', err.message); return []; }),
    ]).then(([allReadings, u, p]) => {
      setUnits(u);
      setProtocols(p);
      const unitMap = Object.fromEntries(u.map(x => [x.id, x]));
      const protoMap = Object.fromEntries(p.map(x => [x.id, x]));

      // Group readings by meter_number + meter_type to form logical meters
      const meterMap = {};
      (Array.isArray(allReadings) ? allReadings : []).forEach(r => {
        const meterKey = `${r.meter_number || 'unknown'}-${r.meter_type}`;
        const proto = protoMap[r.handover_id];
        const unitId = proto?.unit_id || '';

        if (!meterMap[meterKey]) {
          meterMap[meterKey] = {
            id: meterKey,
            meter_number: r.meter_number || '—',
            meter_type: r.meter_type,
            unit_id: unitId,
            unit_label: unitId ? (unitMap[unitId]?.label || unitId) : '—',
            unit_display: r.unit || 'kWh',
            readings: [],
          };
        }
        meterMap[meterKey].readings.push(r);
      });

      // Compute last reading per meter
      const meterList = Object.values(meterMap).map(meter => {
        const sorted = meter.readings.sort((a, b) =>
          (b.created_at || '').localeCompare(a.created_at || '')
        );
        return {
          ...meter,
          last_reading_value: sorted[0]?.reading_value ?? '—',
          last_reading_date: sorted[0]?.created_at?.split('T')[0] ?? '—',
        };
      });
      setMeters(meterList);
    }).catch(err => console.warn('[Meters] load failed:', err.message)).finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleSelectMeter = (meter) => {
    setSelectedMeter(meter);
    const sorted = [...meter.readings].sort((a, b) =>
      (a.created_at || '').localeCompare(b.created_at || '')
    );
    const withConsumption = sorted.map((rd, i) => ({
      ...rd,
      reading_date: rd.created_at?.split('T')[0] || '—',
      consumption: i > 0 ? rd.reading_value - sorted[i - 1].reading_value : null,
    }));
    setReadings(withConsumption);
  };

  const readingFields = [
    { key: 'handover_id', label: 'Übergabeprotokoll', type: 'select', required: true,
      options: protocols.map(p => ({
        value: p.id,
        label: `${p.protocol_type === 'move_in' ? 'Einzug' : 'Auszug'} — ${p.protocol_date} (${p.id.slice(0, 8)})`,
      })) },
    { key: 'meter_type', label: 'Zählertyp', type: 'select', required: true, options: [
      { value: 'electricity', label: 'Strom' },
      { value: 'gas', label: 'Gas' },
      { value: 'water', label: 'Wasser' },
      { value: 'heating', label: 'Heizung' },
    ]},
    { key: 'meter_number', label: 'Zählernummer' },
    { key: 'reading_value', label: 'Zählerstand', type: 'number', required: true },
    { key: 'unit', label: 'Maßeinheit', default: 'kWh', placeholder: 'kWh, m³, etc.' },
    { key: 'photo_url', label: 'Foto-URL', placeholder: '/fotos/zaehler.jpg' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSaveReading = async (data) => {
    const handoverId = data.handover_id;
    await api.post(`/handover-protocols/${handoverId}/meter-readings`, data);
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
          initial={selectedMeter ? {
            handover_id: selectedMeter.readings[0]?.handover_id || '',
            meter_type: selectedMeter.meter_type,
            meter_number: selectedMeter.meter_number,
            unit: selectedMeter.unit_display,
          } : null}
          onSave={handleSaveReading}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
