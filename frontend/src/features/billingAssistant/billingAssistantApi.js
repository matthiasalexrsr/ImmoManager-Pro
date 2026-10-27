import { api } from '../../api';

export const STEPS = [
  { key: 'period', label: 'Objekt & Zeitraum' },
  { key: 'occupancy', label: 'Nutzer & Zeiträume' },
  { key: 'keys', label: 'Verteilerschlüssel' },
  { key: 'costs', label: 'Kosten' },
  { key: 'readings', label: 'Zählerstände' },
  { key: 'check', label: 'Prüfen' },
  { key: 'result', label: 'Abrechnen' },
];

export const KEY_TYPE_LABELS = { area_sqm: 'Fläche', person_count: 'Personen', unit_count: 'Einheiten', consumption: 'Verbrauch' };
export const METER_LABELS = { cold_water: 'Kaltwasser', hot_water: 'Warmwasser', heating: 'Heizung', electricity: 'Strom', gas: 'Gas' };

export const billingAssistantApi = {
  properties: options => api.list('/properties', options),
  guide: (propertyId, periodId, options) => api.get(`/billing/guide?${new URLSearchParams({
    property_id: propertyId, ...(periodId ? { period_id: periodId } : {}) })}`, options),
  createPeriod: body => api.post('/billing/periods', body),
  createKey: body => api.post('/billing/allocation-keys', body),
  addCost: body => api.post('/billing/cost-items', body),
  removeCost: id => api.del(`/billing/cost-items/${encodeURIComponent(id)}`),
  addReading: (meterId, body) => api.post(`/meters/${encodeURIComponent(meterId)}/readings`, { meter_id: meterId, ...body }),
  generate: periodId => api.post(`/billing/periods/${encodeURIComponent(periodId)}/generate`, {}),
};

/** The property's key for a catalogue entry ("area_sqm", "consumption:cold_water"): the one the period uses, else the newest. */
export function keyFor(spec, keys) {
  const [type, meterType] = String(spec || 'area_sqm').split(':');
  const matching = (keys || []).filter(key => key.key_type === type && (!meterType || key.meter_type === meterType));
  const fallback = type === 'consumption' ? (keys || []).filter(key => key.key_type === (meterType === 'cold_water' ? 'person_count' : 'area_sqm')) : [];
  const list = matching.length ? matching : fallback;
  return (list.find(key => key.used) || list[list.length - 1])?.id || '';
}

export function segmentText(segment) {
  const range = `${formatDay(segment.start)}–${formatDay(segment.end)}`;
  if (segment.kind === 'vacancy') return `Leerstand ${range} (${segment.days} Tage)`;
  const persons = segment.persons != null ? `, ${segment.persons} ${segment.persons === 1 ? 'Person' : 'Personen'}` : '';
  return `${segment.tenant || segment.contract_number || 'Mieter'} ${range} (${segment.days} Tage${persons})`;
}

function formatDay(iso) {
  if (!iso) return '—';
  const [year, month, day] = iso.split('-');
  return `${day}.${month}.${year}`;
}
